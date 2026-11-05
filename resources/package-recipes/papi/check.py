#!/usr/bin/env python3
"""Check PAPI component enumeration, preserving disabled component messages."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def validate(text):
    if not re.search(r"(?:PAPI Version|Available components)", text, re.IGNORECASE):
        raise ValueError("PAPI did not initialize and list components")
    if "Compiled-in components:" not in text or not re.search(r"^Name:\s+\S+", text, re.MULTILINE):
        raise ValueError("PAPI output contains no component identity")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        env = dict(os.environ, LC_ALL="C", LD_LIBRARY_PATH=str(args.prefix / "lib") +
                   (":" + os.environ["LD_LIBRARY_PATH"] if os.environ.get("LD_LIBRARY_PATH") else ""))
        result = subprocess.run([str(args.prefix / "bin/papi_component_avail")],
                                env=env, capture_output=True,
                                text=True, timeout=30, check=True)
        validate(result.stdout)
        print(json.dumps({"status": "passed", "check": "papi-component-enumeration",
                          "counter_collection_qualified": False, "component_report": result.stdout}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": "papi-component-enumeration", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
