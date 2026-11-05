"""Build canonical SQLite with bundled Jim Tcl and the exact pinned static zlib."""
from __future__ import annotations
import argparse
import hashlib
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
    tree, work, logs = build / "sqlite-source", build / "sqlite-build", build / "recipe-logs"
    shutil.copytree(source, tree, symlinks=True)
    work.mkdir()
    logs.mkdir()
    rows = []
    env = dict(os.environ, PATH="/usr/bin:/bin", LC_ALL="C", SOURCE_DATE_EPOCH="0")
    for key in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LDFLAGS", "LD_LIBRARY_PATH", "LD_PRELOAD", "MAKEFLAGS", "MFLAGS", "TCLSH", "TCLLIBPATH", "PKG_CONFIG_PATH"):
        env.pop(key, None)

    def run(name, argv, timeout=900):
        output = logs / (name + ".log")
        row = {"name": name, "argv": [str(p) for p in argv], "cwd": str(work), "log": str(output)}
        started = time.monotonic()
        with output.open("w") as stream:
            result = subprocess.run(row["argv"], cwd=work, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        row.update(returncode=result.returncode, elapsed_seconds=time.monotonic() - started)
        rows.append(row)
        (build / "recipe-log.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        if result.returncode:
            raise RuntimeError("Build step failed; read " + str(output))
        return output

    share = prefix / "share/compiler-playground/sqlite"
    share.mkdir(parents=True)
    zlib = json.loads((recipe / "zlib-lock.json").read_text())
    dependency = Path(os.environ.get("CPG_SQLITE_ZLIB_ROOT", "/")).resolve()
    for item in zlib["files"]:
        path = dependency / item["path"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item["bytes"]:
            raise RuntimeError("Exact pinned zlib development file is missing: " + str(path))
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise RuntimeError("Exact pinned zlib development file changed: " + str(path))
        destination = share / "zlib" / item["installed_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    shutil.copy2(recipe / "zlib-lock.json", share / "zlib/source-lock.json")
    zlib_include, zlib_library = share / "zlib/include", share / "zlib/lib"
    flags = "-O2 -g0 -ffile-prefix-map=" + str(build) + "=/usr/src/sqlite"
    run("configure", ["/bin/sh", str(tree / "configure"), "--prefix=" + str(prefix), "--disable-tcl", "--disable-readline",
        "--disable-editline", "--disable-rpath", "--all", "--soname=legacy", "CC=/usr/bin/cc", "CFLAGS=" + flags,
        "CPPFLAGS=-I" + str(zlib_include), "LDFLAGS=-L" + str(zlib_library)])
    # The bundled directory contains only libz.a, so configure's -lz probe and
    # every final link resolve the locked static archive, never host libz.so.
    make = ["/usr/bin/make", f"-j{args.jobs}", "LDFLAGS.zlib=" + str(zlib_library / "libz.a")]
    run("build", make + ["all"])
    run("upstream-generated-source-check", make + ["sourcetest"])
    run("build-public-fuzzcheck", make + ["fuzzcheck"])
    run("upstream-fuzzdata1", [str(work / "fuzzcheck"), "--prng-seed", "1", "--timeout", "10000", "--brief", str(tree / "test/fuzzdata1.db")])
    run("install", make + ["install", "install-pc"])
    dynamic = run("verify-static-zlib-link", ["/usr/bin/ldd", str(prefix / "bin/sqlite3")])
    if "libz.so" in dynamic.read_text():
        raise RuntimeError("The SQLite CLI unexpectedly depends on a host shared zlib")
    pc = prefix / "lib/pkgconfig/sqlite3.pc"
    text = pc.read_text()
    if text.count("prefix=" + str(prefix) + "\n") != 1:
        raise RuntimeError("Unexpected upstream pkg-config prefix")
    text = text.replace("prefix=" + str(prefix) + "\n", "prefix=${pcfiledir}/../..\n", 1)
    if text.count("-lz") != 1:
        raise RuntimeError("The enabled zlib feature is missing from generated linking metadata")
    pc.write_text(text.replace("-lz", "${prefix}/share/compiler-playground/sqlite/zlib/lib/libz.a", 1))
    for name in ("api_probe.c", "extension.c", "check.py"):
        shutil.copy2(recipe / name, share / name)
    for name in ("README.md", "LICENSE.md", "manifest.uuid", "VERSION"):
        shutil.copy2(source / name, share / name)
    shutil.copy2(source / "doc/compile-for-unix.md", share / "compile-for-unix.md")
    amalgamation = share / "amalgamation"
    amalgamation.mkdir()
    for name in ("sqlite3.c", "sqlite3.h", "shell.c"):
        shutil.copy2(work / name, amalgamation / name)
    run("compile-installed-api-probe", ["/usr/bin/cc", "-std=c11", "-O2", "-g0", "-I" + str(prefix / "include"),
        str(share / "api_probe.c"), "-L" + str(prefix / "lib"), "-lsqlite3", "-ldl", "-Wl,-rpath,$ORIGIN/../lib",
        "-o", str(prefix / "bin/cpg-sqlite-api-probe")])
    run("compile-loadable-extension", ["/usr/bin/cc", "-std=c11", "-O2", "-g0", "-fPIC", "-shared",
        "-I" + str(prefix / "include"), str(share / "extension.c"), "-o", str(share / "cpg_extension.so")])
    (share / "profile.json").write_text(json.dumps({
        "id": "sqlite", "version": "3.54.1", "profile": "linux-x86_64-ubuntu24.04-all-sql-features",
        "configure": ["--disable-tcl", "--disable-readline", "--disable-editline", "--disable-rpath", "--all", "--soname=legacy"],
        "zlib": {"enabled": True, "linkage": "Exact existing apt.zlib1g-dev static libz.a; no host libz.so requirement", "source_lock": zlib},
        "upstream_tests": ["make sourcetest", "fuzzcheck --prng-seed 1 --timeout 10000 --brief test/fuzzdata1.db"],
        "upstream_tcl_suite": {"status": "not_run", "reason": "Full Tcl development prerequisites are not installed in this qualification host; bundled Jim Tcl is used only for code generation."},
        "proprietary_TH3": "not_run; separately distributed upstream material",
        "optimization": "-O2 -g0; no -march=native",
        "relocation": "CLI embeds amalgamation; relative shared-library SONAME links, $ORIGIN/../lib C API probe and pcfiledir-relative pkg-config prefix.",
        "benchmark_qualification": "not_run"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
