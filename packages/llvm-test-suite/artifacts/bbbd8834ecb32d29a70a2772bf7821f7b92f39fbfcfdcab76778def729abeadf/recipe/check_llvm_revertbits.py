#!/usr/bin/env python3
"""Future representative native check against an exact upstream output; not run at review."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

REFERENCE_SHA256 = "3b5f6821ed4c5674bdb24c2906e199e07e5ceaa04a43fef57eb8525ff117cdcf"
SOURCE_SHA256 = "21e4b5de4306d2c66a39058502cb930072d82dca4321cf8d2dd98182774fcffe"
REFERENCE = b"0x12345678 -> 0x1e6a2c48\n0x123456789012345 -> 0xa2c48091e6a2c480\nexit 0\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    if hashlib.sha256(REFERENCE).hexdigest() != REFERENCE_SHA256:
        raise RuntimeError("Embedded upstream reference identity changed")
    provenance = json.loads((prefix / "share/cpg/original-source-native-subset-provenance.json").read_text())
    records = {row["file"]: row for row in provenance["files"]}
    checked = []
    with tempfile.TemporaryDirectory(prefix="cpg-llvm-native-check-") as folder:
        for compiler in ("gcc", "clang"):
            relative = "bin/benchmarks/" + compiler + "/revertBits"
            row = records.get(relative, {})
            if (row.get("upstream_original_source_sha256") != SOURCE_SHA256
                    or row.get("upstream_original_reference_sha256") != REFERENCE_SHA256):
                raise RuntimeError("Packaged provenance does not bind the exact upstream example")
            executable = prefix / relative
            if hashlib.sha256(executable.read_bytes()).hexdigest() != row.get("sha256"):
                raise RuntimeError("Selected installed benchmark differs from its delivered binary")
            result = subprocess.run([str(executable)], cwd=folder, env=dict(os.environ, LC_ALL="C"),
                                    capture_output=True, timeout=20)
            # The upstream timeit oracle appends the process exit status to stdout.
            measured = result.stdout + b"exit " + str(result.returncode).encode() + b"\n"
            if measured != REFERENCE:
                raise RuntimeError("Native bit-reversal result differs from the original upstream oracle")
            checked.append(relative)
    print(json.dumps({"status": "passed", "checked": checked,
                      "scope": "representative_gcc_and_clang_bit_reversal_only",
                      "full_suite_qualification": False}))


if __name__ == "__main__":
    main()
