#!/usr/bin/env python3
"""Validate installed APT topology utilities without changing memory policy."""
import argparse
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET


def validate_xml(text):
    root = ET.fromstring(text)
    pus = [obj for obj in root.iter("object") if obj.get("type") == "PU"]
    if root.tag != "topology" or not pus:
        raise ValueError("No processing units in the topology document")
    return {"processing_units": len(pus)}


def validate_numa(text):
    available = re.search(r"available:\s+(\d+)\s+nodes?", text)
    nodes = re.findall(r"^node\s+(\d+)\s+size:\s+(\d+)\s+MB", text, re.MULTILINE)
    if available is None or int(available.group(1)) < 1 or not nodes:
        raise ValueError("numactl did not return a NUMA node and memory size")
    if len({node for node, _ in nodes}) != int(available.group(1)):
        raise ValueError("Declared and enumerated NUMA node counts differ")
    return {"nodes": [{"os_index": int(node), "memory_mb": int(memory)} for node, memory in nodes]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("xml", "numa"))
    args = parser.parse_args()
    argv = ["lstopo-no-graphics", "--of", "xml"] if args.mode == "xml" else ["numactl", "--hardware"]
    try:
        result = subprocess.run(argv, env=dict(os.environ, LC_ALL="C"), capture_output=True,
                                text=True, timeout=30, check=True)
        detail = validate_xml(result.stdout) if args.mode == "xml" else validate_numa(result.stdout)
        print(json.dumps({"status": "passed", "check": args.mode, "details": detail}))
        return 0
    except (OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": args.mode, "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
