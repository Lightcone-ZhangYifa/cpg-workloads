#!/usr/bin/env python3
"""Check hyperfine 1.18 JSON samples, actual repetitions and failed commands."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import tempfile


def validate_result(document, command, runs=3):
    results = document.get("results")
    if not isinstance(results, list) or len(results) != 1 or results[0].get("command") != command:
        raise ValueError("Expected one result for the actual requested command")
    row = results[0]
    samples = row.get("times")
    if not isinstance(samples, list) or len(samples) != runs:
        raise ValueError("The measured sample count differs from --runs")
    for value in samples + [row.get(key) for key in ("mean", "stddev", "median", "user", "system", "min", "max")]:
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Timing values must be finite nonnegative numbers")
    wanted = {"mean": statistics.mean(samples), "median": statistics.median(samples), "stddev": statistics.stdev(samples),
              "min": min(samples), "max": max(samples)}
    for key, expected in wanted.items():
        if not math.isclose(row[key], expected, rel_tol=1e-7, abs_tol=1e-10):
            raise ValueError("Summary statistics disagree with raw measured samples: " + key)
    codes = row.get("exit_codes")
    if codes is not None and (not isinstance(codes, list) or len(codes) != runs
                              or any(type(code) is not int or code != 0 for code in codes)):
        raise ValueError("Successful measurements contained invalid child exit codes")
    return row


def qualify(tool="/usr/bin/hyperfine"):
    environment = dict(os.environ, LC_ALL="C")
    commands = []

    def run(argv):
        result = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=30, check=False)
        commands.append({"argv": argv, "returncode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        return result

    version = run([tool, "--version"])
    if version.returncode != 0 or version.stdout.strip() != "hyperfine 1.18.0":
        raise ValueError("This check requires the pinned hyperfine 1.18.0 CLI/JSON contract")
    with tempfile.TemporaryDirectory(prefix="cpg-hyperfine-") as directory:
        directory = Path(directory)
        marker, child, output = directory / "calls.txt", directory / "child.py", directory / "result.json"
        child.write_text("from pathlib import Path\nimport sys\n"
                         "with Path(sys.argv[1]).open('a') as stream: stream.write('called\\n')\n"
                         "raise SystemExit(int(sys.argv[2]))\n")
        command = shlex.join([sys.executable, "-I", str(child), str(marker), "0"])
        result = run([tool, "--shell=none", "--warmup", "1", "--runs", "3", "--export-json", str(output), command])
        if result.returncode != 0:
            raise ValueError("The successful benchmark command failed")
        document = json.loads(output.read_text())
        row = validate_result(document, command)
        if marker.read_text().splitlines() != ["called"] * 4:
            raise ValueError("Warmup and measured executions did not produce exactly four child calls")
        failed_marker = directory / "failed-call.txt"
        failed_command = shlex.join([sys.executable, "-I", str(child), str(failed_marker), "7"])
        failed = run([tool, "--shell=none", "--runs", "3", failed_command])
        if failed.returncode == 0 or not failed_marker.exists():
            raise ValueError("An executed nonzero-exit command was not reported as a failure")
        failure_calls = failed_marker.read_text().splitlines()
        if failure_calls != ["called"]:
            raise ValueError("A failing command did not stop after its first failed measurement")
    return {"status": "passed", "check": "json-repetitions-and-child-failure", "version": "1.18.0",
            "commands": commands, "measured_result": row, "successful_child_calls": 4,
            "failed_child_calls": len(failure_calls), "failure_returncode": failed.returncode,
            "scope": "Pinned CLI/JSON and actual command execution; not a benchmark result or performance claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", default="/usr/bin/hyperfine")
    args = parser.parse_args()
    try:
        result = qualify(args.tool)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {"status": "failed", "check": "json-repetitions-and-child-failure", "reason": str(error)}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
