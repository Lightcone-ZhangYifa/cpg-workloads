#!/usr/bin/env python3
"""Install the complete locked header library and three upstream example tools."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    source, prefix = args.source.resolve(), args.prefix.resolve()
    shutil.copytree(source, prefix / "share/testlib/source")
    (prefix / "include").mkdir()
    (prefix / "bin").mkdir()
    shutil.copy2(source / "testlib.h", prefix / "include/testlib.h")
    shutil.copy2(source / "LICENSE", prefix / "LICENSE")
    for executable, file in (("testlib-igen", "generators/igen.cpp"),
                             ("testlib-ival", "validators/ival.cpp"),
                             ("testlib-icmp", "checkers/icmp.cpp")):
        argv = ["/usr/bin/g++", "-std=c++17", "-O2", "-march=x86-64", "-mtune=generic",
                "-I" + str(prefix / "include"), str(source / file), "-o", str(prefix / "bin" / executable)]
        print(json.dumps({"argv": argv}), flush=True)
        subprocess.run(argv, check=True)
    helpers = prefix / "share/compiler-playground/testlib"
    shutil.copytree(Path(__file__).parent, helpers)
    (helpers / "profile.json").write_text(json.dumps({"schema_version": 1, "id": "testlib", "profile": "compiled-upstream-examples",
                                                      "compiler_standard": "c++17", "upstream_source_modified": False}, indent=2) + "\n")


if __name__ == "__main__":
    main()
