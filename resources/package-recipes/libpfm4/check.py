#!/usr/bin/env python3
"""Exercise libpfm event enumeration and encoding without opening counters."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def validate(text):
    # -E prints compact event records together with the encoded event value.
    rows = [line for line in text.splitlines()
            if re.search(r"0x[0-9a-fA-F]+", line) and "::" in line]
    if not rows:
        raise ValueError("libpfm returned no encoded named event")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        env = dict(os.environ, LC_ALL="C", LD_LIBRARY_PATH=str(args.prefix / "lib") +
                   (":" + os.environ["LD_LIBRARY_PATH"] if os.environ.get("LD_LIBRARY_PATH") else ""))
        result = subprocess.run([str(args.prefix / "bin/showevtinfo"), "-E"], env=env,
                                capture_output=True, text=True, timeout=30, check=True)
        count = validate(result.stdout)
        print(json.dumps({"status": "passed", "check": "libpfm-event-encoding",
                          "encoded_events": count, "counter_collection_qualified": False}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": "libpfm-event-encoding", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
