"""Build the complete upstream XZ CMake profile without altering its source.

The binary prefix is fixed: upstream gettext embeds the absolute locale path.
Both liblzma linkage forms, CLI tools/scripts, messages and source docs remain.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    source, build, prefix = (p.resolve() for p in (args.source, args.build, args.prefix))
    recipe = Path(__file__).resolve().parent
    tree, shared, static = build / "xz-source", build / "shared", build / "static"
    shutil.copytree(source, tree, symlinks=True)
    logs = build / "recipe-logs"
    logs.mkdir()
    rows = []
    env = dict(os.environ, PATH="/usr/bin:/bin", LC_ALL="C", SOURCE_DATE_EPOCH="0")
    # Private CMake can need its declared build-only LD_LIBRARY_PATH binding.
    for key in ("CC", "CXX", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LDFLAGS", "LD_PRELOAD",
                "MAKEFLAGS", "MFLAGS", "CMAKE_PREFIX_PATH", "XZ_DEFAULTS", "XZ_OPT"):
        env.pop(key, None)
    cmake = Path(env.get("CPG_CMAKE", "/usr/bin/cmake")).resolve()
    ninja = Path(env.get("CPG_NINJA", "/usr/bin/ninja")).resolve()
    ctest = cmake.with_name("ctest")

    def run(name, argv, timeout=900):
        output = logs / (name + ".log")
        row = {"name": name, "argv": [str(p) for p in argv], "cwd": str(tree), "log": str(output)}
        started = time.monotonic()
        with output.open("w") as stream:
            result = subprocess.run(row["argv"], cwd=tree, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        row.update(returncode=result.returncode, elapsed_seconds=time.monotonic() - started)
        rows.append(row)
        (build / "recipe-log.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        if result.returncode:
            raise RuntimeError("Build step failed; read " + str(output))

    common = [cmake, "-S", tree, "-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=" + str(ninja),
              "-DCMAKE_C_COMPILER=/usr/bin/cc", "-DCMAKE_BUILD_TYPE=Release",
              "-DCMAKE_C_FLAGS_RELEASE=-O2 -g0 -DNDEBUG -ffile-prefix-map=" + str(build) + "=/usr/src/xz",
              "-DCMAKE_INSTALL_PREFIX=" + str(prefix), "-DCMAKE_INSTALL_LIBDIR=lib",
              "-DCMAKE_INSTALL_DOCDIR=share/doc/xz", "-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib",
              "-DCMAKE_INSTALL_RPATH_USE_LINK_PATH=OFF", "-DXZ_NLS=ON", "-DXZ_THREADS=posix",
              "-DXZ_DOC=ON", "-DXZ_TOOL_SCRIPTS=ON", "-DXZ_TOOL_XZ=ON",
              "-DXZ_TOOL_XZDEC=ON", "-DXZ_TOOL_LZMADEC=ON", "-DXZ_TOOL_LZMAINFO=ON"]
    run("configure-shared", common + ["-B", shared, "-DBUILD_SHARED_LIBS=ON", "-DBUILD_TESTING=ON"])
    run("build-shared-tools-and-tests", [cmake, "--build", shared, "--parallel", args.jobs])
    run("upstream-test-discovery", [ctest, "--test-dir", shared, "--show-only=json-v1"])
    junit = logs / "upstream-ctest.xml"
    run("upstream-ctest", [ctest, "--test-dir", shared, "--output-on-failure", "--no-tests=error",
                           "--parallel", args.jobs, "--output-junit", junit])
    report = ET.parse(junit).getroot()
    test_summary = {key: int(report.attrib.get(key, "0")) for key in ("tests", "failures", "disabled")}
    if test_summary["tests"] < 1 or test_summary["failures"]:
        raise RuntimeError("Official CTest run did not produce passing test evidence")
    run("install-shared-and-tools", [cmake, "--install", shared])
    run("configure-static", common + ["-B", static, "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TESTING=OFF"])
    run("build-static-library", [cmake, "--build", static, "--target", "liblzma", "--parallel", args.jobs])
    shutil.copy2(static / "liblzma.a", prefix / "lib/liblzma.a")
    share = prefix / "share/compiler-playground/xz"
    share.mkdir(parents=True)
    for name in ("api_probe.c", "check.py"):
        shutil.copy2(recipe / name, share / name)
    for name in ("README", "INSTALL", "COPYING", "COPYING.0BSD", "COPYING.GPLv2", "COPYING.LGPLv2.1"):
        shutil.copy2(source / name, share / name)
    shutil.copy2(shared / "CMakeCache.txt", share / "CMakeCache-shared.txt")
    shutil.copy2(static / "CMakeCache.txt", share / "CMakeCache-static.txt")
    compiler = ["/usr/bin/cc", "-std=c11", "-O2", "-g0", "-I" + str(prefix / "include"), str(share / "api_probe.c")]
    run("compile-shared-api-probe", compiler + ["-L" + str(prefix / "lib"), "-llzma", "-ldl", "-pthread",
              "-Wl,-rpath,$ORIGIN/../lib", "-o", prefix / "bin/cpg-xz-api-probe"])
    run("compile-static-api-probe", compiler + ["-DCPG_STATIC_LIBRARY=1", "-DLZMA_API_STATIC",
              prefix / "lib/liblzma.a", "-ldl", "-pthread", "-o", prefix / "bin/cpg-xz-api-probe-static"])
    (share / "profile.json").write_text(json.dumps({
        "id": "xz", "version": "5.8.4", "profile": "upstream-cmake-full-tools-nls-fixed-prefix",
        "fixed_prefix": str(prefix), "source_modified": False, "shared_and_static_libraries": True,
        "nls": True, "locale_directory": str(prefix / "share/locale"), "threads": "posix",
        "upstream_ctest": test_summary, "source_man_pages": "installed",
        "translated_man_pages": "not_run: Git snapshot needs separate po4a/update-po; all raw translation sources retained",
        "build_tools": {"cmake": str(cmake), "ninja": str(ninja), "ctest": str(ctest)},
        "relocatable": False, "reason": "Upstream gettext embeds the absolute locale directory. Use exactly this prefix for binary installation.",
        "benchmark_qualification": "not_run"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
