"""Build upstream native zlib-ng in a private tree; keep shared/static libraries."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    source, build, prefix = (p.resolve() for p in (args.source, args.build, args.prefix))
    recipe = Path(__file__).resolve().parent
    tree, logs = build / "zlib-ng", build / "recipe-logs"
    shutil.copytree(source, tree, symlinks=True)
    logs.mkdir()
    rows = []
    env = dict(os.environ, PATH="/usr/bin:/bin", LC_ALL="C", SOURCE_DATE_EPOCH="0")
    for key in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LDFLAGS", "LD_LIBRARY_PATH", "LD_PRELOAD", "MAKEFLAGS", "MFLAGS", "CONFIG_SHELL"):
        env.pop(key, None)
    env.update(CC="/usr/bin/cc", CFLAGS="-O2 -g0 -ffile-prefix-map=" + str(tree) + "=/usr/src/zlib-ng")
    def run(name, argv, timeout=600):
        output = logs / (name + ".log")
        row = {"name": name, "argv": [str(p) for p in argv], "cwd": str(tree), "log": str(output)}
        started = time.monotonic()
        with output.open("w") as stream:
            result = subprocess.run(row["argv"], cwd=tree, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        row.update(returncode=result.returncode, elapsed_seconds=time.monotonic() - started)
        rows.append(row)
        (build / "recipe-log.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        if result.returncode:
            raise RuntimeError("Build step failed; read " + str(output))
    run("configure", ["/bin/bash", str(tree / "configure"), "--prefix=" + str(prefix), "--shared"])
    make = ["/usr/bin/make", f"-j{args.jobs}"]
    run("build", make + ["all"])
    run("upstream-tests", make + ["test"])
    # Execute upstream infcover directly; do not claim gcov coverage percentages.
    run("build-upstream-infcover", make + ["infcover"])
    run("upstream-infcover", [str(tree / "infcover")])
    # Independent prefixes use relative links/RUNPATH, never the global loader cache.
    run("install", make + ["install", "LDCONFIG=/bin/true"])
    pc = prefix / "lib/pkgconfig/zlib-ng.pc"
    text = pc.read_text()
    if text.count("prefix=" + str(prefix) + "\n") != 1:
        raise RuntimeError("Unexpected upstream pkg-config prefix")
    pc.write_text(text.replace("prefix=" + str(prefix) + "\n", "prefix=${pcfiledir}/../..\n", 1))
    share = prefix / "share/compiler-playground/zlib-ng"
    share.mkdir(parents=True)
    for name in ("api_probe.c", "check.py"):
        shutil.copy2(recipe / name, share / name)
    for name in ("README.md", "PORTING.md", "LICENSE.md"):
        shutil.copy2(source / name, share / name)
    shutil.copy2(tree / "configure.log", share / "configure.log")
    for name in ("example.c", "minigzip.c", "infcover.c"):
        shutil.copy2(source / "test" / name, share / name)
    (prefix / "bin").mkdir(exist_ok=True)
    shutil.copy2(tree / "minigzip", prefix / "bin/zlib-ng-minigzip")
    compiler = ["/usr/bin/cc", "-std=c11", "-O2", "-g0", "-DWITH_GZFILEOP", "-I" + str(prefix / "include"), str(share / "api_probe.c")]
    run("compile-shared-api-probe", compiler + ["-L" + str(prefix / "lib"), "-lz-ng", "-ldl", "-Wl,-rpath,$ORIGIN/../lib", "-o", str(prefix / "bin/cpg-zlib-ng-api-probe")])
    run("compile-static-api-probe", compiler + ["-DCPG_STATIC_LIBRARY=1", str(prefix / "lib/libz-ng.a"), "-ldl", "-o", str(prefix / "bin/cpg-zlib-ng-api-probe-static")])
    (share / "profile.json").write_text(json.dumps({
        "id": "zlib-ng", "version": "2.3.3", "profile": "linux-x86_64-ubuntu24.04-native-abi",
        "zlib_compat": False, "optimized_dispatch": "upstream configure defaults; no -march=native added",
        "gzip_file_api": True, "shared_and_static_libraries": True,
        "upstream_tests": ["make test", "make infcover && ./infcover"],
        "google_test_cmake_suite": "not_run; separate build/test profile",
        "relocation": "Native libz-ng SONAME, relative library links, relative RUNPATH and pcfiledir metadata; no global loader-cache updates.",
        "benchmark_qualification": "not_run"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
