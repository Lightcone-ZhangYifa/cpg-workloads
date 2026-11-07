#!/usr/bin/env python3
"""Run meaningful acceptance against the explicit independent installation prefix."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    prefix = args.prefix.resolve()
    share = prefix / "share/cpg"
    adjacent = Path(__file__).resolve().parent.parent / "source-lock.json"
    lock_path = adjacent if adjacent.is_file() else share / "source-lock.json"
    lock = json.loads(lock_path.read_text())
    resource = lock["resource"]
    checks = share / "checks"
    for name, expected in lock["checks_sha256"].items():
        with (checks / name).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise SystemExit("Installed acceptance input changed: " + name)
    if resource == "bril":
        command = [sys.executable, checks / "bril_check.py", "--source", share / "source/bril", "--deno", prefix / "runtime/deno"]
    elif resource == "xdsl":
        command = [prefix / "venv/bin/python", checks / "xdsl_check.py"]
    elif resource == "libfirm":
        command = [sys.executable, checks / "libfirm_check.py", "--include", prefix / "include", "--library", prefix / "lib/libfirm.a", "--upstream-tests", prefix / "libexec/upstream-tests"]
    elif resource == "cparser":
        command = [sys.executable, checks / "cparser_check.py", "--cparser", prefix / "bin/cparser"]
    else:
        raise SystemExit("unknown resource")
    command += ["--out", args.out.resolve()]
    raise SystemExit(subprocess.run([str(x) for x in command], timeout=600).returncode)


if __name__ == "__main__":
    main()
