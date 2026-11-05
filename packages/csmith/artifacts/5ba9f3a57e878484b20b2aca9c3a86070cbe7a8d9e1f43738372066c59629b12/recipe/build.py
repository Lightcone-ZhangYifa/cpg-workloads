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
    modifications = []
    if args.resource == "csmith":
        # This upstream helper walks parent directories itself, ignoring Git's
        # ceiling. A checked metadata-only change in the build copy prevents an
        # enclosing framework checkout from becoming Csmith's reported version.
        path = source / "CMakeLists.txt"
        text = path.read_text()
        marker = 'set(GIT_HASH "$Format:%h$")'
        if text.count(marker) != 1:
            raise RuntimeError("Unexpected Csmith archive version-discovery expression")
        path.write_text(text.replace(marker, 'set(GIT_HASH "0cdc710")'))
        modifications.append({"file": "CMakeLists.txt", "purpose": "Use the exact locked archive commit for version metadata; prevent parent Git identity leakage.",
                              "original_sha256": hashlib.sha256(text.encode()).hexdigest(),
                              "build_copy_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

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
