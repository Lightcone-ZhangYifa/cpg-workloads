#!/usr/bin/env python3
"""Build the exact ClangBuildAnalyzer source without mutating retained material."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    cmake = os.environ.get("CPG_CMAKE", "/usr/bin/cmake")
    ninja = os.environ.get("CPG_NINJA", "/usr/bin/ninja")
    for argv in ([cmake, "-S", args.source, "-B", args.build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                  "-DCMAKE_C_COMPILER=/usr/bin/gcc", "-DCMAKE_CXX_COMPILER=/usr/bin/g++",
                  "-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic", "-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic",
                  "-DCMAKE_C_FLAGS_RELEASE=-O2 -UNDEBUG", "-DCMAKE_CXX_FLAGS_RELEASE=-O2 -UNDEBUG",
                  "-DCMAKE_MAKE_PROGRAM=" + ninja, "-DCMAKE_INSTALL_PREFIX=" + str(args.prefix)],
                 [cmake, "--build", args.build, "--parallel", args.jobs], [cmake, "--install", args.build]):
        command = [str(x) for x in argv]
        print(json.dumps({"argv": command}), flush=True)
        subprocess.run(command, check=True)
    shutil.copytree(args.source, args.prefix / "share/clang-build-analyzer/source")
    shutil.copytree(Path(__file__).parent, args.prefix / "share/compiler-playground/clang-build-analyzer")


if __name__ == "__main__":
    main()
