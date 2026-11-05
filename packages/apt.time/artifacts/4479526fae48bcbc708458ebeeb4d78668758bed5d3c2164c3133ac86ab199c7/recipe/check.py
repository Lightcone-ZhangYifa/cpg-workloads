#!/usr/bin/env python3
"""Check GNU time's resource report and child exit-code propagation."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


FORMAT = "wall_seconds=%e\nuser_seconds=%U\nsystem_seconds=%S\nmax_rss_kib=%M\nexit_status=%x"


def parse_report(text, expected_exit):
    rows = [line.split("=", 1) for line in text.strip().splitlines()]
    expected = {"wall_seconds", "user_seconds", "system_seconds", "max_rss_kib", "exit_status"}
    if any(len(row) != 2 for row in rows) or len(rows) != len(expected) or {row[0] for row in rows} != expected:
        raise ValueError("GNU time produced an incomplete or duplicate resource report")
    result = {key: float(value) for key, value in rows}
    if any(not math.isfinite(value) or value < 0 for value in result.values()):
        raise ValueError("GNU time reported invalid resource values")
    if result["exit_status"] != expected_exit:
        raise ValueError("GNU time reported the wrong child exit status")
    if not result["exit_status"].is_integer() or not result["max_rss_kib"].is_integer():
        raise ValueError("GNU time exit status and resident memory must be integral values")
    if result["max_rss_kib"] <= 0:
        raise ValueError("The allocating child had no observed resident memory")
    return result


def qualify(tool="/usr/bin/time"):
    commands, reports = [], []
    environment = dict(os.environ, LC_ALL="C")
    version = subprocess.run([tool, "--version"], env=environment, capture_output=True,
                             text=True, timeout=10, check=False)
    commands.append({"argv": [tool, "--version"], "returncode": version.returncode,
                     "stdout": version.stdout, "stderr": version.stderr})
    if version.returncode != 0 or "GNU Time" not in version.stdout:
        raise ValueError("The selected executable is not a working GNU time")
    child = ("import sys; a=bytearray(4*1024*1024); "
             "a[::4096]=b'x'*1024; print('pages='+str(sum(a[::4096]))); sys.exit(int(sys.argv[1]))")
    with tempfile.TemporaryDirectory(prefix="cpg-gnu-time-") as directory:
        for status in (0, 7):
            output = Path(directory) / f"exit-{status}.txt"
            argv = [tool, "--quiet", "--format", FORMAT, "--output", str(output),
                    sys.executable, "-I", "-c", child, str(status)]
            result = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=20, check=False)
            commands.append({"argv": argv, "returncode": result.returncode,
                             "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode != status or result.stdout != "pages=122880\n":
                raise ValueError("GNU time changed the child's exit status or output")
            report = output.read_text()
            reports.append({"raw": report, "parsed": parse_report(report, status)})
    return {"status": "passed", "check": "resource-accounting-and-exit-status",
            "tool": str(Path(tool).absolute()), "commands": commands, "reports": reports,
            "scope": "Resource report and child exit propagation only; samples are not benchmark scores."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", default="/usr/bin/time")
    args = parser.parse_args()
    try:
        result = qualify(args.tool)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = {"status": "failed", "check": "resource-accounting-and-exit-status", "reason": str(error)}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
