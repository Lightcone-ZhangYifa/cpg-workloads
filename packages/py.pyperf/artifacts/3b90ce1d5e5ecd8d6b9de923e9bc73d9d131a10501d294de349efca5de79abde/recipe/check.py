#!/usr/bin/env python3
"""Exercise official pyperf workers, retained raw JSON and the public result API."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile


def require_version(actual, expected):
    if actual != expected:
        raise ValueError(f"Expected pyperf {expected}; observed {actual}")


def validate_samples(values, mean, median, stdev):
    if len(values) != 6 or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("Expected six finite positive measured values")
    for observed, expected in ((mean, statistics.mean(values)), (median, statistics.median(values)),
                               (stdev, statistics.stdev(values))):
        if not math.isfinite(observed) or not math.isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("Public statistics disagree with the raw measured values")


def qualify(expected_version, version_only=False):
    import pyperf

    version = importlib.metadata.version("pyperf")
    require_version(version, expected_version)
    require_version(pyperf.__version__, expected_version)
    identity = {"version": version, "interpreter": sys.executable, "module": pyperf.__file__}
    if version_only:
        return {"status": "passed", "check": "distribution-version", **identity}
    commands = []

    def execute(argv):
        process = subprocess.run(argv, capture_output=True, text=True, timeout=90, check=False)
        commands.append({"argv": argv, "returncode": process.returncode,
                         "stdout": process.stdout, "stderr": process.stderr})
        return process

    with tempfile.TemporaryDirectory(prefix="cpg-pyperf-") as directory:
        root = Path(directory)
        output = root / "runner.json"
        command = [sys.executable, "-I", str(Path(__file__).with_name("runner.py")),
                   "--processes", "2", "--values", "3", "--warmups", "1", "--loops", "2",
                   "--output", str(output)]
        result = execute(command)
        if result.returncode != 0 or not output.is_file():
            raise ValueError("Official Runner did not produce a result: " + result.stderr)
        raw = json.loads(output.read_text())
        suite = pyperf.BenchmarkSuite.load(str(output))
        if suite.get_benchmark_names() != ["cpg-integer-reduction"]:
            raise ValueError("The official result has an unexpected benchmark identity")
        benchmark = suite.get_benchmark("cpg-integer-reduction")
        values = list(benchmark.get_values())
        runs = list(benchmark.get_runs())
        if len(runs) != 2 or any(run.get_loops() != 2 or len(run.values) != 3 or len(run.warmups) != 1 for run in runs):
            raise ValueError("Worker count, loops, measurements or warmups differ from the requested protocol")
        validate_samples(values, benchmark.mean(), benchmark.median(), benchmark.stdev())
        metadata = benchmark.get_metadata()
        if benchmark.get_unit() != "second" or Path(metadata["python_executable"]).resolve() != Path(sys.executable).resolve():
            raise ValueError("The result unit or worker interpreter differs")
        roundtrip = root / "roundtrip.json"
        suite.dump(str(roundtrip))
        if list(pyperf.BenchmarkSuite.load(str(roundtrip)).get_benchmark("cpg-integer-reduction").get_values()) != values:
            raise ValueError("Official serialization round trip changed the measured values")
        stats = execute([sys.executable, "-I", "-m", "pyperf", "stats", str(output)])
        if stats.returncode != 0 or "Mean" not in stats.stdout or "Median" not in stats.stdout:
            raise ValueError("The official statistics CLI could not read the Runner output")
        called = root / "failed-child-called.txt"
        failing_child = "from pathlib import Path; Path(" + repr(str(called)) + ").write_text('called\\n'); raise SystemExit(7)"
        failure = execute([sys.executable, "-I", "-m", "pyperf", "command", "--processes", "1",
                           "--values", "1", "--warmups", "0", "--loops", "1", "--output", str(root / "failed.json"),
                           sys.executable, "-I", "-c", failing_child])
        if (failure.returncode == 0 or (root / "failed.json").exists()
                or not called.is_file() or called.read_text() != "called\n"
                or "Command failed with exit code 7" not in failure.stderr):
            raise ValueError("A failing measured command was incorrectly accepted as a valid result")
    return {"status": "passed", "check": "official-runner-json-and-failure", **identity,
            "raw_runner_json": raw, "values": values, "mean": benchmark.mean(),
            "median": benchmark.median(), "stdev": benchmark.stdev(),
            "workers": len(runs), "loops_per_value": 2, "serialization_roundtrip": "passed",
            "failed_command_rejected": True, "commands": commands,
            "scope": "Official pyperf Runner/API/CLI operation with a deliberately small qualification workload; not statistically stable performance results or an official compiler-benchmark score."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default="2.10.0")
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    try:
        result = qualify(args.expected_version, args.version_only)
    except Exception as error:
        result = {"status": "failed", "reason": str(error), "error_type": type(error).__name__}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
