#!/usr/bin/env python3
"""Build Google Benchmark static libraries and its standalone upstream tests."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

SELECTED = ("cxx11_test", "basic_benchmark", "register_benchmark_test", "args_product_test",
            "repetitions_benchmark", "reporter_output_test", "skip_with_error_test", "donotoptimize_test")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "build", "prefix"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    cmake = Path(os.environ.get("CPG_CMAKE", "/usr/bin/cmake")).resolve()
    ninja = Path(os.environ.get("CPG_NINJA", "/usr/bin/ninja")).resolve()
    ctest = cmake.with_name("ctest")

    def run(argv, *, capture=False):
        command = [str(item) for item in argv]
        print(json.dumps({"argv": command}), flush=True)
        return subprocess.run(command, check=True, capture_output=capture, text=capture)

    run([ctest, "--version"])
    run([cmake, "-S", args.source, "-B", args.build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
         "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_CXX_COMPILER=/usr/bin/g++",
         "-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic", "-DCMAKE_INSTALL_PREFIX=" + str(args.prefix),
         "-DCMAKE_INSTALL_LIBDIR=lib", "-DBUILD_SHARED_LIBS=OFF", "-DBENCHMARK_DOWNLOAD_DEPENDENCIES=OFF",
         "-DCMAKE_DISABLE_FIND_PACKAGE_Git=TRUE",
         "-DBENCHMARK_ENABLE_TESTING=ON", "-DBENCHMARK_ENABLE_GTEST_TESTS=OFF", "-DBENCHMARK_ENABLE_ASSEMBLY_TESTS=OFF",
         "-DBENCHMARK_ENABLE_LIBPFM=OFF", "-DBENCHMARK_ENABLE_RUST_BINDINGS=OFF", "-DBENCHMARK_ENABLE_LTO=OFF"])
    run([cmake, "--build", args.build, "--parallel", args.jobs])
    available = json.loads(run([ctest, "--test-dir", args.build, "--show-only=json-v1"], capture=True).stdout)
    selected = []
    for test in available["tests"]:
        if test["name"] in SELECTED:
            executable, *arguments = test["command"]
            executable = Path(executable)
            if executable.parent != args.build / "test" or any(str(args.build) in part or str(args.source) in part for part in arguments):
                raise RuntimeError("Selected upstream test is not independently executable after installation")
            selected.append({"id": test["name"], "executable": executable.name, "arguments": arguments})
    if {item["id"] for item in selected} != set(SELECTED):
        raise RuntimeError("A selected upstream standalone test disappeared")
    # Run all ordinary standalone tests once during source preparation. The
    # PMU-specific test is retained, but no hardware-counter execution is claimed.
    run([ctest, "--test-dir", args.build, "--output-on-failure", "--parallel", "1",
         "--timeout", "120", "-E", "^perf_counters_test$", "--output-junit", args.build / "upstream-tests.xml"])
    run([cmake, "--install", args.build])
    for path in (args.prefix / "lib/pkgconfig").glob("*.pc"):
        text = path.read_text()
        expected = "prefix=" + str(args.prefix) + "\n"
        if text.count(expected) != 1:
            raise RuntimeError("Unexpected upstream pkg-config prefix")
        path.write_text(text.replace(expected, "prefix=${pcfiledir}/../..\n"))
    destination = args.prefix / "libexec/google-benchmark"
    destination.mkdir(parents=True)
    for executable in sorted((args.build / "test").iterdir()):
        if executable.is_file() and executable.read_bytes()[:4] == b"\x7fELF":
            shutil.copy2(executable, destination / executable.name)
    helpers = args.prefix / "share/compiler-playground/google-benchmark"
    shutil.copytree(Path(__file__).parent, helpers)
    (helpers / "upstream-test-commands.json").write_text(json.dumps(selected, indent=2) + "\n")
    (helpers / "profile.json").write_text(json.dumps({"schema_version": 1, "id": "google-benchmark", "version": "1.10.0",
        "libraries": "static", "target": "Ubuntu 24.04 x86_64", "upstream_source_modified": False,
        "source_ctest_count": len(available["tests"]) - sum(t["name"] == "perf_counters_test" for t in available["tests"]),
        "installed_selected_tests": selected, "excluded_ctest_names": ["perf_counters_test"],
        "disabled_optional_features": ["GoogleTest tests", "assembly FileCheck tests", "Rust", "libpfm PMU counters", "LTO"],
        "pkgconfig_change": "prefix=${pcfiledir}/../.."}, indent=2) + "\n")
    shutil.copytree(args.source, args.prefix / "share/google-benchmark/source")


if __name__ == "__main__":
    main()
