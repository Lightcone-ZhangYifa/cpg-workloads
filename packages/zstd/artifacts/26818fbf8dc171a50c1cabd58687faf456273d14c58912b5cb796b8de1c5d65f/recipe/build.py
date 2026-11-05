"""Build upstream's native Zstd profile without auto-linking optional host codecs."""
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
    tree, logs = build / "zstd", build / "recipe-logs"
    shutil.copytree(source, tree, symlinks=True)
    logs.mkdir()
    rows = []
    env = dict(os.environ, PATH="/usr/bin:/bin", LC_ALL="C", SOURCE_DATE_EPOCH="0")
    for key in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LDFLAGS", "LD_LIBRARY_PATH", "LD_PRELOAD", "MAKEFLAGS", "MFLAGS", "ZSTD_CLEVEL", "ZSTD_NBTHREADS"):
        env.pop(key, None)

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

    flags = "-O2 -g0 -ffile-prefix-map=" + str(tree) + "=/usr/src/zstd"
    make = ["/usr/bin/make", f"-j{args.jobs}", "CC=/usr/bin/cc", "CFLAGS=" + flags,
            "HAVE_ZLIB=0", "HAVE_LZMA=0", "HAVE_LZ4=0", "PREFIX=" + str(prefix)]
    run("build", make + ["default"])
    run("upstream-check", make + ["check"], timeout=900)
    run("install", make + ["install"])
    pc = prefix / "lib/pkgconfig/libzstd.pc"
    text = pc.read_text()
    if text.count("prefix=" + str(prefix) + "\n") != 1:
        raise RuntimeError("Unexpected upstream pkg-config prefix")
    pc.write_text(text.replace("prefix=" + str(prefix) + "\n", "prefix=${pcfiledir}/../..\n", 1))
    share = prefix / "share/compiler-playground/zstd"
    share.mkdir(parents=True)
    for name in ("api_probe.c", "check.py"):
        shutil.copy2(recipe / name, share / name)
    for name in ("LICENSE", "COPYING", "README.md", "TESTING.md"):
        shutil.copy2(source / name, share / name)
    for name in ("golden-decompression", "golden-decompression-errors"):
        shutil.copytree(source / "tests" / name, share / name, symlinks=True)
    run("compile-installed-api-probe", ["/usr/bin/cc", "-std=c11", "-O2", "-g0", "-I" + str(prefix / "include"),
        str(share / "api_probe.c"), "-L" + str(prefix / "lib"), "-lzstd", "-ldl", "-Wl,-rpath,$ORIGIN/../lib",
        "-o", str(prefix / "bin/cpg-zstd-api-probe")])
    (share / "profile.json").write_text(json.dumps({
        "id": "zstd", "version": "v1.5.7", "profile": "linux-x86_64-ubuntu24.04-native-zstd",
        "multithreading": True, "foreign_cli_codecs": {"gzip": False, "xz": False, "lz4": False},
        "optimization": "-O2 -g0; no -march=native", "upstream_tests": ["make check"],
        "relocation": "Relative SONAME links, $ORIGIN/../lib C API probe and pcfiledir-relative pkg-config prefix.",
        "benchmark_qualification": "not_run"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
