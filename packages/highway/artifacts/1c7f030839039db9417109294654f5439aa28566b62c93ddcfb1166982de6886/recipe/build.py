#!/usr/bin/env python3
"""Build Highway shared/static libraries and selected upstream standalone tests."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

TESTS = ("aligned_allocator_test", "base_test", "bit_set_test", "highway_test", "targets_test",
         "skeleton_test", "arithmetic_test", "logical_test", "memory_test", "reduction_test",
         "copy_test", "find_test", "transform_test", "sort_unit_test", "thread_pool_test")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    cmake = Path(os.environ.get("CPG_CMAKE", "/usr/bin/cmake")).resolve()
    ninja = Path(os.environ.get("CPG_NINJA", "/usr/bin/ninja")).resolve()
    evidence = args.prefix / "share/compiler-playground/highway"
    evidence.mkdir(parents=True)
    commands = []

    def run(label, argv):
        command = [str(v) for v in argv]
        print(json.dumps({"label": label, "argv": command}), flush=True)
        with (evidence / (label + ".stdout")).open("wb") as stdout, (evidence / (label + ".stderr")).open("wb") as stderr:
            completed = subprocess.run(command, stdout=stdout, stderr=stderr)
        commands.append({"label": label, "argv": command, "returncode": completed.returncode})
        (evidence / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if completed.returncode:
            raise RuntimeError("Build command failed: " + label)

    for kind in ("static", "shared"):
        directory = args.build / kind
        run("configure-" + kind, [cmake, "-S", args.source, "-B", directory, "-G", "Ninja",
            "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_CXX_COMPILER=/usr/bin/g++", "-DCMAKE_CXX_STANDARD=17",
            "-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic",
            "-DCMAKE_INSTALL_PREFIX=" + str(args.prefix), "-DCMAKE_INSTALL_LIBDIR=lib",
            "-DCMAKE_INSTALL_RPATH=$ORIGIN", "-DHWY_ENABLE_CONTRIB=ON",
            "-DHWY_ENABLE_EXAMPLES=OFF", "-DHWY_ENABLE_INSTALL=ON",
            "-DHWY_TEST_STANDALONE=ON", "-DHWY_ENABLE_TESTS=" + ("ON" if kind == "static" else "OFF"),
            "-DBUILD_SHARED_LIBS=" + ("ON" if kind == "shared" else "OFF")])
        targets = ["hwy", "hwy_contrib", "hwy_test"]
        if kind == "static":
            targets.extend(TESTS)
        run("build-" + kind, [cmake, "--build", directory, "--parallel", args.jobs, "--target", *targets])
        run("install-" + kind, [cmake, "--install", directory])
    destination = args.prefix / "libexec/highway"
    destination.mkdir(parents=True)
    for test in TESTS:
        shutil.copy2(args.build / "static/tests" / test, destination / test)
    for path in (args.prefix / "lib/pkgconfig").glob("*.pc"):
        lines = path.read_text().splitlines()
        expected = "prefix=" + str(args.prefix)
        if lines.count(expected) != 1:
            raise RuntimeError("Unexpected upstream pkg-config prefix")
        lines[lines.index(expected)] = "prefix=${pcfiledir}/../.."
        path.write_text("\n".join(lines) + "\n")
    shutil.copytree(args.source, args.prefix / "share/highway/source")
    for name in ("build.py", "check.py", "api.cpp"):
        shutil.copy2(Path(__file__).with_name(name), evidence / name)
    (evidence / "profile.json").write_text(json.dumps({
        "id": "highway", "version": "1.4.0", "libraries": ["shared", "static"],
        "source_modified": False, "contrib": True, "upstream_selected_tests": list(TESTS),
        "test_mode": "official HWY_TEST_STANDALONE=ON", "dispatch": "upstream supported runtime targets",
        "cmake_export": "shared hwy targets; static archives remain available for explicit linking",
        "unperformed": ["remaining upstream test binaries", "physical PMU", "cross-architecture", "performance comparison"]
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
