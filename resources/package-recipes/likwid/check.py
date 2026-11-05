#!/usr/bin/env python3
"""Check LIKWID topology parsing; this does not qualify MSR/PCI counters."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def validate(text):
    count = re.search(r"(?:Threads\s+per\s+core|HWThread|Hardware Thread)", text, re.IGNORECASE)
    identity = re.search(r"CPU\s+(?:name|type)|Sockets?\s*:", text, re.IGNORECASE)
    if not count or not identity:
        raise ValueError("LIKWID returned no CPU identity/thread topology")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = subprocess.run([str(args.prefix / "bin/likwid-topology")],
                                env=dict(os.environ, LC_ALL="C"), capture_output=True,
                                text=True, timeout=30, check=True)
        validate(result.stdout)
        print(json.dumps({"status": "passed", "check": "likwid-topology",
                          "counter_collection_qualified": False}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": "likwid-topology", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
