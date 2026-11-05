#!/usr/bin/env python3
"""Build a locked generator, keeping all original upstream material intact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

RESOURCES = ("csmith", "yarpgen-scalar", "yarpgen-loop")
UPSTREAM_TESTS = ("type_test", "data_test", "expr_test", "gen_test")


def apply_csmith_fixes(source, manifest=None):
    """Apply the two explicit fixes only to the exact pinned build-copy bytes."""
    manifest = manifest or Path(__file__).with_name("csmith-build-fixes.json")
    document = json.loads(manifest.read_text())
    if document.get("upstream_commit") != "0cdc710315cfee9035e22ef4363ca479270d1934" or [p["path"] for p in document.get("patches", [])] != ["CMakeLists.txt", "runtime/volatile_runtime.c"]:
        raise RuntimeError("The exact two Csmith build fixes are required")
    prepared, modifications = [], []
    for patch in document["patches"]:
        path = source / patch["path"]
        raw = path.read_bytes()
        text = raw.decode()
        if hashlib.sha256(raw).hexdigest() != patch["original_sha256"] or text.count(patch["before"]) != 1:
            raise RuntimeError("Csmith build-fix input differs from its locked original: " + patch["path"])
        revised = text.replace(patch["before"], patch["after"]).encode()
        if hashlib.sha256(revised).hexdigest() != patch["patched_sha256"]:
            raise RuntimeError("Csmith build-fix output differs from its declared bytes")
        prepared.append((path, revised))
        modifications.append({"file": patch["path"], "purpose": patch["purpose"], "original_sha256": patch["original_sha256"], "build_copy_sha256": patch["patched_sha256"], "patch_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()})
    for path, revised in prepared:
        path.write_bytes(revised)
    return modifications


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", choices=RESOURCES, required=True)
    for key in ("source", "build", "prefix"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    original = args.prefix / "share" / args.resource / "source"
    shutil.copytree(args.source, original)
    source = args.build / "upstream"
    shutil.copytree(args.source, source)
    build = args.build / "cmake"
    cmake = Path(os.environ.get("CPG_CMAKE", "/usr/bin/cmake")).resolve()
    ninja = Path(os.environ.get("CPG_NINJA", "/usr/bin/ninja")).resolve()
    environment = dict(os.environ, SOURCE_DATE_EPOCH="0")
    environment.pop("LD_PRELOAD", None)
    modifications = apply_csmith_fixes(source) if args.resource == "csmith" else []

    def run(argv):
        command = [str(x) for x in argv]
        print(json.dumps({"argv": command}), flush=True)
        subprocess.run(command, check=True, env=environment)

    command = [cmake, "-S", source, "-B", build, "-G", "Ninja",
               "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_COMPILER=/usr/bin/gcc",
               "-DCMAKE_CXX_COMPILER=/usr/bin/g++", "-DCMAKE_MAKE_PROGRAM=" + str(ninja),
               "-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic",
               "-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic",
               "-DCMAKE_C_FLAGS_RELEASE=-O2 -UNDEBUG", "-DCMAKE_CXX_FLAGS_RELEASE=-O2 -UNDEBUG",
               "-DCMAKE_INSTALL_PREFIX=" + str(args.prefix), "-DCMAKE_INSTALL_LIBDIR=lib",
               "-DCMAKE_DISABLE_FIND_PACKAGE_Git=TRUE"]
    if args.resource == "csmith":
        command.append("-DM4=" + os.environ.get("CPG_M4", "/usr/bin/m4"))
    run(command)
    run([cmake, "--build", build, "--parallel", args.jobs])
    if args.resource == "csmith":
        run([cmake, "--install", build])
    else:
        (args.prefix / "bin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / "yarpgen", args.prefix / "bin/yarpgen")
        if args.resource == "yarpgen-loop":
            destination = args.prefix / "libexec/yarpgen-loop"
            destination.mkdir(parents=True)
            for name in UPSTREAM_TESTS:
                shutil.copy2(build / name, destination / name)

    helpers = args.prefix / "share/compiler-playground" / args.resource
    shutil.copytree(Path(__file__).parent, helpers)
    profile = {"schema_version": 1, "id": args.resource, "target": "Ubuntu 24.04 x86_64",
               "source_date_epoch": 0, "assertions_enabled": True, "original_material_modified": False,
               "build_copy_modifications": modifications,
               "installed_upstream_tests": list(UPSTREAM_TESTS) if args.resource == "yarpgen-loop" else [],
               "test_oracle": "Fixed-seed byte reproducibility and same-compiler O0/O2 checksum agreement; no claim of an independent compiler oracle or official benchmark score."}
    (helpers / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")


if __name__ == "__main__":
    main()
