#!/usr/bin/env python3
"""Exercise installed libcpuid CPU decoding and raw-data round trips."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def validate_report(text: str) -> dict[str, object]:
    """Reject a successful process that did not actually identify any CPU."""
    vendors = re.findall(r"vendor_str\s*:\s*`([^']+)'", text)
    architectures = re.findall(r"^\s*arch\s*:\s*(\S+)", text, re.MULTILINE)
    logical = [int(n) for n in re.findall(r"tot_logical\s*:\s*(-?\d+)", text)]
    if "CPUID is present" not in text or not vendors or not architectures:
        raise ValueError("CPU identity fields are absent from the decoded report")
    if not logical or any(n <= 0 for n in logical):
        raise ValueError("The decoded report has no positive logical CPU count")
    if "Error identifying" in text or "nothing to report" in text:
        raise ValueError("The decoder reported an identification error")
    return {"vendors": vendors, "architectures": architectures,
            "reported_logical_cpus": logical}


def run(prefix: Path, evidence_dir: Path) -> dict[str, object]:
    binary = prefix / "bin/cpuid_tool"
    env = dict(os.environ, LC_ALL="C")
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    raw = evidence_dir / "cpuid.raw.txt"
    first = subprocess.run([str(binary), "--save=" + str(raw), "--report"],
                           env=env, text=True, capture_output=True, timeout=30, check=True)
    second = subprocess.run([str(binary), "--load=" + str(raw), "--report"],
                            env=env, text=True, capture_output=True, timeout=30, check=True)
    (evidence_dir / "live-report.txt").write_text(first.stdout)
    (evidence_dir / "roundtrip-report.txt").write_text(second.stdout)
    (evidence_dir / "diagnostics.txt").write_text(first.stderr + second.stderr)
    identity = validate_report(first.stdout)
    if raw.stat().st_size == 0 or first.stdout != second.stdout:
        raise ValueError("Raw CPU serialization did not reproduce the decoded report")
    negative_results = []
    for argv in [["--load=" + str(evidence_dir / "does-not-exist.raw"), "--report"],
                 ["--cpg-intentionally-unknown-option"]]:
        failed = subprocess.run([str(binary), *argv], env=env, capture_output=True, text=True, timeout=30)
        if failed.returncode == 0:
            raise ValueError("Missing input or unsupported option was accepted")
        negative_results.append({"argv": argv, "returncode": failed.returncode, "stdout": failed.stdout, "stderr": failed.stderr})
    (evidence_dir / "negative-cases.json").write_text(json.dumps(negative_results, indent=2)+"\n")
    api = subprocess.run([str(prefix / "bin/libcpuid-api-check")], env=env,
                         text=True, capture_output=True, timeout=15, check=True)
    paths = [line.partition("=")[2] for line in api.stdout.splitlines() if line.startswith("loaded_library=")]
    if len(paths) != 1 or Path(paths[0]).resolve(strict=True) != (prefix / "lib/libcpuid.so").resolve(strict=True):
        raise ValueError("The API probe resolved a library outside this installed prefix")
    if "libcpuid API passed:" not in api.stdout:
        raise ValueError("The installed public API check did not report success")
    (evidence_dir / "api-check.txt").write_text(api.stdout)
    return {"status": "passed", "check": "libcpuid-decode-roundtrip-and-api",
            "negative_cases": negative_results, "identity": identity, "raw_bytes": raw.stat().st_size,
            "scope": "CPU identity and serialization; no clock, MSR or performance measurement"}


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
            with tempfile.TemporaryDirectory(prefix="libcpuid-check-") as temporary:
                result = run(args.prefix.resolve(), Path(temporary))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "check": "libcpuid-decode-roundtrip-and-api",
                          "reason": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
