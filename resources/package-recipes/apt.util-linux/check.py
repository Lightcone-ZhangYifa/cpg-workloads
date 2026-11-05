#!/usr/bin/env python3
"""Read CPU inventory or bind a disposable child to an already allowed CPU."""
import argparse
import json
import os
import subprocess
import sys


def inventory(text):
    rows = json.loads(text).get("lscpu", [])
    fields = {row["field"].rstrip(":"): row["data"] for row in rows}
    if not fields.get("Architecture") or int(fields.get("CPU(s)", 0)) <= 0:
        raise ValueError("lscpu did not return architecture and positive CPU count")
    return fields


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inventory", "affinity"))
    args = parser.parse_args()
    env = dict(os.environ, LC_ALL="C")
    try:
        if args.mode == "inventory":
            result = subprocess.run(["lscpu", "--json"], env=env, capture_output=True,
                                    text=True, timeout=15, check=True)
            detail = inventory(result.stdout)
        else:
            allowed = sorted(os.sched_getaffinity(0))
            if not allowed:
                raise ValueError("The process has no allowed CPUs")
            command = ["taskset", "--cpu-list", str(allowed[0]), sys.executable, "-c",
                       "import json,os; print(json.dumps(sorted(os.sched_getaffinity(0))))"]
            result = subprocess.run(command, env=env, capture_output=True,
                                    text=True, timeout=15, check=True)
            child = json.loads(result.stdout)
            if child != [allowed[0]] or sorted(os.sched_getaffinity(0)) != allowed:
                raise ValueError("Child affinity did not match, or parent affinity changed")
            detail = {"parent_allowed_cpus": allowed, "child_allowed_cpus": child}
        print(json.dumps({"status": "passed", "check": args.mode, "details": detail}))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": args.mode, "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
