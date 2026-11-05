#!/usr/bin/env python3
"""Build the complete upstream libdivide test/tool profile at a baseline ISA."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    cmake = Path(os.environ.get("CPG_CMAKE", "/usr/bin/cmake")).resolve()
    ninja = Path(os.environ.get("CPG_NINJA", "/usr/bin/ninja")).resolve()
    if not cmake.is_file() or not ninja.is_file():
        raise RuntimeError("The pinned CMake and Ninja build dependencies must be installed or explicitly bound")
    options = ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_LIBDIR=lib",
               "-DCMAKE_INSTALL_PREFIX=" + str(args.prefix), "-DCMAKE_MAKE_PROGRAM=" + str(ninja),
               "-DCMAKE_C_COMPILER=/usr/bin/cc", "-DCMAKE_CXX_COMPILER=/usr/bin/c++",
               "-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic", "-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic",
               "-DLIBDIVIDE_BUILD_TESTS=ON", "-DLIBDIVIDE_BUILD_FUZZERS=OFF", "-DLIBDIVIDE_ENABLE_SANITIZERS=OFF",
               "-DMARCH_NATIVE=OFF", "-DLIBDIVIDE_SSE2=ON", "-DLIBDIVIDE_AVX2=OFF", "-DLIBDIVIDE_AVX512=OFF",
               "-DLIBDIVIDE_NEON=OFF", "-DLIBDIVIDE_SVE=OFF", "-DLIBDIVIDE_SVE2=OFF"]
    for argv in ([cmake, "-S", args.source, "-B", args.build, *options],
                 [cmake, "--build", args.build, "--parallel", args.jobs],
                 [cmake, "--install", args.build]):
        command = [str(item) for item in argv]
        print(json.dumps({"argv": command}), flush=True)
        subprocess.run(command, check=True)
    profile = args.prefix / "share/compiler-playground/libdivide/profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(json.dumps({"schema_version": 1, "id": "libdivide", "version": "5.4.0",
                                  "target": "Ubuntu 24.04 x86_64", "simd": ["SSE2"],
                                  "march_native": False, "upstream_source_modified": False,
                                  "cross_platform_qualification": "not_run"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
