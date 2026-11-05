#!/usr/bin/env python3
"""Separate perf event parsing from a bounded, explicitly selected PMU read."""
import argparse
import csv
import io
import json
import math
import os
import re
import subprocess
import sys


def blocked_reason(text):
    patterns = (
        (r"not permitted|permission|access.*denied|perf_event_paranoid", "permission"),
        (r"not supported|no such device|cannot find PMU|no PMU|<not counted>", "unsupported-pmu"),
    )
    return next((reason for pattern, reason in patterns if re.search(pattern, text, re.IGNORECASE)), None)


def validate_counts(text):
    found = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 3 or row[0].strip().startswith("#"):
            continue
        event = row[2].strip()
        for requested in ("cycles", "instructions"):
            if event == requested or event.endswith("/" + requested + "/") or event.startswith(requested + ":"):
                count = float(row[0].strip())
                if not math.isfinite(count) or count <= 0:
                    raise ValueError("A requested counter is not finite and positive")
                found[requested] = found.get(requested, 0.0) + count
    if set(found) != {"cycles", "instructions"}:
        raise ValueError("Both cycles and instructions must contain positive counts")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("events", "counters"))
    args = parser.parse_args()
    env = dict(os.environ, LC_ALL="C")
    try:
        if args.mode == "events":
            result = subprocess.run(["perf", "list", "--raw-dump"], env=env,
                                    text=True, capture_output=True, timeout=30, check=True)
            if not re.search(r"(?:cycles|instructions|cpu-clock|task-clock)", result.stdout):
                raise ValueError("perf did not enumerate an expected core or software event")
            detail = {"counter_collection_qualified": False}
        else:
            allowed = sorted(os.sched_getaffinity(0))
            if not allowed:
                print(json.dumps({"status": "blocked", "check": "perf-counter-read", "reason": "No allowed CPUs"}))
                return 77
            argv = ["perf", "stat", "-x", ",", "-e", "cycles,instructions", "--", sys.executable,
                    "-c", "print(sum(i * i for i in range(150000)))"]
            result = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=30,
                                    preexec_fn=lambda: os.sched_setaffinity(0, {allowed[0]}), check=False)
            reason = blocked_reason(result.stderr)
            if reason:
                print(json.dumps({"status": "blocked", "check": "perf-counter-read",
                                  "reason": reason, "diagnostic": result.stderr[-12000:]}))
                return 77
            if result.returncode != 0:
                raise ValueError("perf stat failed: " + result.stderr[-4000:])
            detail = {"counts": validate_counts(result.stderr), "cpu": allowed[0],
                      "scope": "One bounded collection probe; not a benchmark result"}
        print(json.dumps({"status": "passed", "check": args.mode, "details": detail}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": args.mode, "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
