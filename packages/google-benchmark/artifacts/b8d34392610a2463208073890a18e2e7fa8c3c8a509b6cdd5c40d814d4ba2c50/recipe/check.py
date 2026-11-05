#!/usr/bin/env python3
"""Verify actual static-library consumers and selected upstream regressions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

LEGACY_TESTS = [
    ("cxx11_test", ["--benchmark_min_time=0.01s"]),
    ("basic_test", ["--benchmark_min_time=0.01s"]),
    ("register_benchmark_test", ["--benchmark_min_time=0.01s"]),
    ("args_product_test", ["--benchmark_min_time=0.01s"]),
    ("repetitions_test", ["--benchmark_min_time=0.01s", "--benchmark_repetitions=3"]),
    ("reporter_output_test", ["--benchmark_min_time=0.01s"]),
    ("skip_with_error_test", ["--benchmark_min_time=0.01s"]),
    ("donotoptimize_test", ["--benchmark_min_time=0.01s"]),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--case", choices=("compile-link-json", "upstream-regressions"), required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    environment = dict(os.environ, LC_ALL="C")
    for key in list(environment):
        if key.startswith("BENCHMARK_") or key in {"CPATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "LIBRARY_PATH", "LD_LIBRARY_PATH", "LD_PRELOAD"}:
            environment.pop(key)
    result = {"status": "running", "case": args.case, "prefix": str(prefix), "commands": [],
              "official_benchmark": False, "performance_improvement_claimed": False,
              "static_library_sha256": hashlib.sha256((prefix / "lib/libbenchmark.a").read_bytes()).hexdigest()}

    def run(argv, *, expected=0):
        command = [str(item) for item in argv]
        completed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=180)
        row = {"argv": command, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
        result["commands"].append(row)
        if completed.returncode != expected:
            raise RuntimeError("Unexpected command result: " + json.dumps(row))
        return completed

    try:
        if args.case == "compile-link-json":
            with tempfile.TemporaryDirectory(prefix="cpg-gbench-check-") as directory:
                temporary = Path(directory)
                for label, filename, with_main in (("custom-main", "api.cpp", False), ("library-main", "api_main.cpp", True)):
                    executable = temporary / label
                    libraries = [prefix / "lib/libbenchmark_main.a"] if with_main else []
                    libraries.append(prefix / "lib/libbenchmark.a")
                    run(["/usr/bin/g++", "-std=c++17", "-O2", "-I" + str(prefix / "include"),
                         Path(__file__).with_name(filename), *libraries, "-pthread", "-lrt", "-o", executable])
                    completed = run([executable, "--benchmark_repetitions=2", "--benchmark_format=json"])
                    report = json.loads(completed.stdout)
                    rows = [row for row in report.get("benchmarks", []) if row.get("run_type", "iteration") == "iteration"]
                    if len(rows) != 2 or any(row.get("iterations") != 256 for row in rows):
                        raise RuntimeError("The API consumer did not execute its exact iterations and repetitions")
                    for row in rows:
                        if row.get("error_occurred") or row.get("time_unit") not in {"ns", "us", "ms", "s"}:
                            raise RuntimeError("The library reported a failed or untyped run")
                        for field in ("cpu_time", "real_time"):
                            if not isinstance(row.get(field), (int, float)) or not math.isfinite(row[field]) or row[field] <= 0:
                                raise RuntimeError("The library did not produce a finite positive measurement")
                        if not with_main and (row.get("argument") != 64 or row.get("items_per_second", 0) <= 0):
                            raise RuntimeError("Registered argument/custom counter/items did not reach JSON output")
                    rejected = run([executable, "--cpg_unrecognized_flag=true"], expected=1)
                    if "unrecognized" not in rejected.stderr.lower():
                        raise RuntimeError("Unknown CLI flag did not produce an explicit rejection diagnostic")
                result.update(consumers=["custom main + libbenchmark", "upstream main + libbenchmark_main + libbenchmark"],
                              repetitions_per_consumer=2, iterations_per_repetition=256,
                              structured_output="validated", invalid_option="rejected")
        else:
            manifest = prefix / "share/compiler-playground/google-benchmark/upstream-test-commands.json"
            if manifest.is_file():
                tests = json.loads(manifest.read_text())
                directory = prefix / "libexec/google-benchmark"
                result["execution_profile"] = "installed-upstream-tests"
            else:
                if args.build is None:
                    raise RuntimeError("A legacy selector check needs its original build directory")
                directory = args.build / "test"
                tests = [{"id": name, "executable": name, "arguments": arguments} for name, arguments in LEGACY_TESTS]
                result["execution_profile"] = "legacy-selector-build-tests"
            expected = dict(LEGACY_TESTS)
            if (not isinstance(tests, list) or len(tests) != len(expected)
                    or {test["executable"]: test["arguments"] for test in tests} != expected):
                raise RuntimeError("The regression manifest must contain all eight upstream tests with their exact arguments")
            for test in tests:
                run([directory / test["executable"], *test["arguments"]])
            result.update(upstream_cases_passed=len(tests), upstream_test_sources_modified=False,
                          physical_pmu="not_run", GoogleTest_matrix="not_run")
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
