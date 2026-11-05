#!/usr/bin/env python3
"""Build simdjson and original self-contained upstream regressions offline."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

TESTS = (
    "unicode_tests.cpp", "padded_string_tests.cpp", "fractured_json_tests.cpp",
    "dom/array_reverse_tests.cpp", "dom/big_integer_tests.cpp", "dom/integer_tests.cpp",
    "dom/json_path_tests.cpp", "dom/random_string_number_tests.cpp", "dom/nan_inf_tests.cpp",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "build", "prefix"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    cmake = Path(os.environ.get("CPG_CMAKE", "/usr/bin/cmake")).resolve()
    ninja = Path(os.environ.get("CPG_NINJA", "/usr/bin/ninja")).resolve()
    evidence = args.prefix / "share/compiler-playground/simdjson"
    evidence.mkdir(parents=True)
    commands = []

    def run(label, argv):
        command = [str(v) for v in argv]
        print(json.dumps({"label": label, "argv": command}), flush=True)
        with (evidence / (label + ".stdout")).open("wb") as stdout, (evidence / (label + ".stderr")).open("wb") as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr)
        commands.append({"label": label, "argv": command, "returncode": result.returncode})
        (evidence / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError("Build command failed: " + label)

    run("configure", [cmake, "-S", args.source, "-B", args.build, "-G", "Ninja",
        "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_CXX_COMPILER=/usr/bin/g++", "-DCMAKE_CXX_STANDARD=17",
        "-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic",
        "-DCMAKE_INSTALL_PREFIX=" + str(args.prefix), "-DCMAKE_INSTALL_LIBDIR=lib",
        "-DBUILD_SHARED_LIBS=ON", "-DSIMDJSON_BUILD_STATIC_LIB=ON",
        "-DSIMDJSON_DEVELOPER_MODE=OFF", "-DSIMDJSON_ALLOW_DOWNLOADS=OFF",
        "-DSIMDJSON_INSTALL=ON", "-DSIMDJSON_ENABLE_THREADS=ON"])
    run("build", [cmake, "--build", args.build, "--parallel", args.jobs])
    run("install", [cmake, "--install", args.build])
    for path in (args.prefix / "lib/pkgconfig").glob("*.pc"):
        lines = path.read_text().splitlines()
        old = "prefix=" + str(args.prefix)
        if lines.count(old) != 1:
            raise RuntimeError("Unexpected pkg-config prefix")
        lines[lines.index(old)] = "prefix=${pcfiledir}/../.."
        path.write_text("\n".join(lines) + "\n")
    destination = args.prefix / "libexec/simdjson"
    destination.mkdir(parents=True)
    library = args.prefix / "lib/libsimdjson_static.a"
    if not library.exists():
        raise RuntimeError("The upstream static library was not installed")
    for name in TESTS:
        test = args.source / "tests" / name
        run("compile-" + test.stem, ["/usr/bin/g++", "-std=c++17", "-O2", "-march=x86-64", "-mtune=generic",
            "-I" + str(args.prefix / "include"), "-I" + str(args.source / "tests"),
            test, library, "-pthread", "-o", destination / test.stem])
    for name in ("build.py", "check.py", "api.cpp"):
        shutil.copy2(Path(__file__).with_name(name), evidence / name)
    shutil.copytree(args.source, args.prefix / "share/simdjson/source")
    (evidence / "profile.json").write_text(json.dumps({
        "id": "simdjson", "version": "5.0.5", "source_modified": False,
        "libraries": ["shared", "static"], "dispatch": "upstream runtime-selected supported implementations",
        "upstream_standalone_tests": list(TESTS), "compile_standard": "C++17",
        "unperformed": ["full developer CMake suite requiring unadmitted external simdjson-data and CPM dependencies",
                         "external competitive benchmarks", "C++26 static reflection", "cross-platform", "performance qualification"]
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
