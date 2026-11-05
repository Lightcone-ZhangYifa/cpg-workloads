#!/usr/bin/env python3
"""Execute original Highway tests and actual shared/static dispatch consumers."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

TESTS = ("aligned_allocator_test", "base_test", "bit_set_test", "highway_test", "targets_test",
         "skeleton_test", "arithmetic_test", "logical_test", "memory_test", "reduction_test",
         "copy_test", "find_test", "transform_test", "sort_unit_test", "thread_pool_test")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--case", choices=("upstream", "api"), required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    environment = dict(os.environ, LC_ALL="C")
    for key in tuple(environment):
        if key.startswith("GTEST_") or key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "LIBRARY_PATH", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
            environment.pop(key, None)
    result = {"status": "running", "case": args.case, "prefix": str(prefix), "commands": []}

    def run(argv):
        command = [str(x) for x in argv]
        completed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=300)
        result["commands"].append({"argv": command, "returncode": completed.returncode,
                                  "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode:
            raise RuntimeError("An installed consumer or upstream test failed")
        return completed

    try:
        profile = json.loads((prefix / "share/compiler-playground/highway/profile.json").read_text())
        if profile.get("version") != "1.4.0" or profile.get("upstream_selected_tests") != list(TESTS):
            raise RuntimeError("The exact complete test selection is missing")
        if args.case == "upstream":
            tests = []
            for name in TESTS:
                executable = prefix / "libexec/highway" / name
                listed = run([executable, "--gtest_list_tests", "--gtest_filter=*"])
                names = [line.strip() for line in listed.stdout.splitlines() if line.startswith("  ") and line.strip()]
                if not names:
                    raise RuntimeError("An upstream executable listed no tests")
                completed = run([executable, "--gtest_filter=*"])
                combined = completed.stdout + completed.stderr
                executions = re.findall(r"^=== .+:$", completed.stderr, flags=re.MULTILINE)
                if len(executions) != len(names) or not completed.stderr.rstrip().endswith("Success."):
                    raise RuntimeError("An upstream executable did not execute every listed test")
                tests.append({"name": name, "listed_cases": len(names), "executed_cases": len(executions),
                              "test_listing": listed.stdout + listed.stderr})
            result.update(upstream_test_executables_passed=len(tests), test_listings=tests, source_modified=False)
        else:
            with tempfile.TemporaryDirectory(prefix="cpg-highway-check-") as directory:
                temporary = Path(directory)
                result["consumers"] = []
                for kind in ("shared", "static"):
                    executable = temporary / kind
                    library = prefix / "lib" / ("libhwy.so" if kind == "shared" else "libhwy.a")
                    run(["/usr/bin/g++", "-std=c++17", "-O2", "-DHWY_COMPILE_ALL_ATTAINABLE=1",
                         "-I" + str(prefix / "include"), "-I" + str(Path(__file__).parent),
                         Path(__file__).with_name("api.cpp"), library, "-pthread",
                         "-Wl,-rpath," + str(prefix / "lib"), "-o", executable])
                    completed = run([executable])
                    rows = []
                    for line in completed.stdout.splitlines():
                        parts = line.split()
                        if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) != 39:
                            raise RuntimeError("Consumer did not report all boundary/alignment cases")
                        rows.append({"target": parts[0], "cases": int(parts[1])})
                    if not rows or len({row["target"] for row in rows}) != len(rows):
                        raise RuntimeError("Consumer did not execute unique supported targets")
                    result["consumers"].append({"link": kind, "targets": rows,
                        "oracle": "exact scalar uint32 arithmetic and guard regions", "empty_and_unaligned_inputs": True})
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
