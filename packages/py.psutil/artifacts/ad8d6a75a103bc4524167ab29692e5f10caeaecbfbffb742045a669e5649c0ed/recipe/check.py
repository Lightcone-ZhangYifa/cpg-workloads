#!/usr/bin/env python3
"""Observe and reap a real child using the selected psutil installation."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile

CHILD = r'''import json, os, sys
memory = bytearray(16 * 1024 * 1024)
for offset in range(0, len(memory), 4096):
    memory[offset] = 3
with open(sys.argv[1], "wb") as stream:
    stream.write(b"cpg-psutil-probe\n")
    stream.flush()
    checksum = sum(number * number for number in range(20000))
    print(json.dumps({"pid": os.getpid(), "checksum": checksum}), flush=True)
    if sys.stdin.readline().strip() != "finish":
        sys.exit(9)
sys.exit(7)
'''


def require_version(actual, expected):
    if actual != expected:
        raise ValueError(f"Expected psutil {expected}; observed {actual}")


def validate_observation(row, *, pid, parent_pid, opened_file):
    if row["pid"] != pid or row["ppid"] != parent_pid:
        raise ValueError("The observed process identity is wrong")
    for key in ("create_time", "rss", "vms", "cpu_user", "cpu_system"):
        if not isinstance(row[key], (int, float)) or not math.isfinite(row[key]) or row[key] < 0:
            raise ValueError("Missing, negative or nonfinite process metric: " + key)
    if row["create_time"] <= 0 or row["rss"] < 16 * 1024 * 1024 or row["vms"] < row["rss"]:
        raise ValueError("The touched child memory allocation was not observed")
    if row["threads"] < 1 or row["file_descriptors"] < 3 or opened_file not in row["open_files"]:
        raise ValueError("Child thread/file-descriptor observations are incomplete")
    return row


def qualify(expected_version, version_only=False):
    import psutil

    version = importlib.metadata.version("psutil")
    require_version(version, expected_version)
    require_version(psutil.__version__, expected_version)
    identity = {"version": version, "interpreter": sys.executable, "module": psutil.__file__}
    if version_only:
        return {"status": "passed", "check": "distribution-version", **identity}
    with tempfile.TemporaryDirectory(prefix="cpg-psutil-") as directory:
        opened = str(Path(directory) / "held-open.bin")
        argv = [sys.executable, "-I", "-c", CHILD, opened]
        child = psutil.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        try:
            if not select.select([child.stdout], [], [], 15)[0]:
                raise ValueError("The real child did not report readiness")
            ready = json.loads(child.stdout.readline())
            if ready != {"pid": child.pid, "checksum": 2666466670000}:
                raise ValueError("Child computation or identity differs")
            with child.oneshot():
                memory, cpu = child.memory_info(), child.cpu_times()
                observed = {"pid": child.pid, "ppid": child.ppid(), "create_time": child.create_time(),
                            "rss": memory.rss, "vms": memory.vms, "cpu_user": cpu.user,
                            "cpu_system": cpu.system, "threads": child.num_threads(),
                            "file_descriptors": child.num_fds(),
                            "open_files": [item.path for item in child.open_files()]}
            validate_observation(observed, pid=child.pid, parent_pid=os.getpid(), opened_file=opened)
            if not child.is_running() or child not in psutil.Process().children():
                raise ValueError("The process-tree query did not find the controlled child")
            child.stdin.write("finish\n")
            child.stdin.flush()
            exit_code = child.wait(timeout=15)
            remainder, stderr = child.stdout.read(), child.stderr.read()
            if exit_code != 7 or child.is_running() or remainder or stderr:
                raise ValueError("Child completion/exit-status propagation differs")
        finally:
            if child.is_running():
                child.kill()
                child.wait(timeout=15)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(directory)
        cpus = psutil.cpu_count(logical=True)
        if not isinstance(cpus, int) or cpus < 1 or not 0 <= memory.available <= memory.total or memory.total <= 0:
            raise ValueError("System CPU/memory observations are invalid")
        if not 0 <= disk.free <= disk.total or disk.total <= 0:
            raise ValueError("Filesystem capacity observation is invalid")
        system = {"logical_cpus": cpus, "memory_total_bytes": memory.total,
                  "memory_available_bytes": memory.available, "disk_total_bytes": disk.total,
                  "disk_free_bytes": disk.free}
    return {"status": "passed", "check": "child-process-resource-observation", **identity,
            "child": observed, "child_ready": ready, "child_exit_code": exit_code,
            "child_reaped": True, "system": system,
            "scope": "Own native Linux child, procfs metrics and filesystem capacity; no privileged foreign-process or sensor qualification."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default="7.2.2")
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    try:
        result = qualify(args.expected_version, args.version_only)
    except (Exception,) as error:
        result = {"status": "failed", "reason": str(error), "error_type": type(error).__name__}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

# Definition-routing fixture: this alternate recipe must be packed and run.
