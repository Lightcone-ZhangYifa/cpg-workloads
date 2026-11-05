#!/usr/bin/env python3
"""Decode the current x86 CPU without MSR access or clock measurement."""
import json
import os
import re
import subprocess


def validate(text):
    if not re.search(r'vendor_id\s*=\s*"[^"\n]+"', text):
        raise ValueError("cpuid output has no decoded vendor_id")
    if not re.search(r"family\s*=\s*", text) or not re.search(r"model\s*=\s*", text):
        raise ValueError("cpuid output has no decoded family/model")


def main():
    try:
        result = subprocess.run(["cpuid", "-1"], env=dict(os.environ, LC_ALL="C"),
                                capture_output=True, text=True, timeout=20, check=True)
        validate(result.stdout)
        print(json.dumps({"status": "passed", "check": "cpuid-decoded-identity"}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": "cpuid-decoded-identity", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
