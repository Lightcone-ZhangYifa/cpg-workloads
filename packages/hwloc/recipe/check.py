#!/usr/bin/env python3
"""Validate live topology, XML replay, synthetic topology and the hwloc C API."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def parse_topology(text: str) -> tuple[dict[str, int], list[tuple[str, ...]]]:
    root = ET.fromstring(text)
    if root.tag != "topology":
        raise ValueError("The output is not an hwloc topology document")
    objects = list(root.iter("object"))
    counts = dict(Counter(item.get("type", "") for item in objects))
    if counts.get("Machine") != 1 or counts.get("PU", 0) < 1:
        raise ValueError("A topology must contain one Machine and at least one PU")
    pu_indices = [obj.get("os_index") for obj in objects if obj.get("type") == "PU"]
    if None in pu_indices or len(pu_indices) != len(set(pu_indices)):
        raise ValueError("Processing units have absent or duplicated OS indices")
    signature = [(obj.get("type", ""), obj.get("os_index", ""),
                  obj.get("cpuset", ""), obj.get("nodeset", ""),
                  obj.get("cache_size", ""), obj.get("local_memory", ""))
                 for obj in objects]
    return counts, signature


def run(prefix: Path, evidence: Path) -> dict[str, object]:
    binary = prefix / "bin/lstopo-no-graphics"
    env = dict(os.environ, LC_ALL="C")
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)

    def command(arguments: list[str], output_name: str) -> str:
        result = subprocess.run([str(binary), *arguments], env=env, capture_output=True,
                                text=True, timeout=30, check=True)
        (evidence / output_name).write_text(result.stdout)
        return result.stdout

    live = command(["--of", "xml"], "live.xml")
    counts, signature = parse_topology(live)
    replay = command(["--input", str(evidence / "live.xml"), "--input-format", "xml",
                      "--of", "xml"], "replayed.xml")
    if parse_topology(replay) != (counts, signature):
        raise ValueError("Topology identity, CPU sets or memory/cache sizes changed after XML replay")
    synthetic = command(["--input", "node:2 core:2 pu:2", "--input-format", "synthetic",
                         "--of", "xml"], "synthetic.xml")
    synthetic_counts, _ = parse_topology(synthetic)
    for kind, expected in (("NUMANode", 2), ("Core", 4), ("PU", 8)):
        if synthetic_counts.get(kind) != expected:
            raise ValueError("Synthetic " + kind + " count does not match the requested topology")
    malformed = evidence / "malformed.xml"
    malformed.write_text("<topology><object type='Machine'></topology>\n")
    negatives = [["--input", str(malformed), "--input-format", "xml", "--of", "xml"],
                 ["--of", "cpg-intentionally-invalid-output-format"]]
    negative_results = []
    for argv in negatives:
        failed = subprocess.run([str(binary), *argv], env=env, capture_output=True, text=True, timeout=30)
        if failed.returncode == 0:
            raise ValueError("Malformed input or unsupported option was accepted")
        negative_results.append({"argv": argv, "returncode": failed.returncode, "stdout": failed.stdout, "stderr": failed.stderr})
    (evidence / "negative-cases.json").write_text(json.dumps(negative_results, indent=2)+"\n")
    api = subprocess.run([str(prefix / "bin/hwloc-api-check")], env=env, text=True,
                         capture_output=True, timeout=15, check=True)
    paths = [line.partition("=")[2] for line in api.stdout.splitlines() if line.startswith("loaded_library=")]
    if len(paths) != 1 or Path(paths[0]).resolve(strict=True) != (prefix / "lib/libhwloc.so").resolve(strict=True):
        raise ValueError("The API probe resolved a library outside this installed prefix")
    if "hwloc API passed:" not in api.stdout:
        raise ValueError("The installed public API check did not report success")
    (evidence / "api-check.txt").write_text(api.stdout)
    return {"status": "passed", "check": "hwloc-core-topology-roundtrip-and-api",
            "negative_cases": negative_results, "live_object_counts": counts, "synthetic_object_counts": synthetic_counts,
            "scope": "CPU/NUMA/cache/LinuxIO with native Linux sysfs PCI; external libpciaccess, GPU and GUI plugins are not included"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.evidence_dir:
            args.evidence_dir.mkdir(parents=True, exist_ok=True)
            result = run(args.prefix.resolve(), args.evidence_dir.resolve())
        else:
            with tempfile.TemporaryDirectory(prefix="hwloc-check-") as temporary:
                result = run(args.prefix.resolve(), Path(temporary))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": "hwloc-core-topology-roundtrip-and-api",
                          "reason": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
