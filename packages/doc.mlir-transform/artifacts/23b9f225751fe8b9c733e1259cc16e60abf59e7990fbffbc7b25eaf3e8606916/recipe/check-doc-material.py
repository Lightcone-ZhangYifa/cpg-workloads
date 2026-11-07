#!/usr/bin/env python3
"""Validate source bytes and exact index locations; no tool qualification."""
from pathlib import Path
import argparse
import hashlib
import json

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--root", type=Path, required=True)
a = p.parse_args()
manifest = json.loads((a.root / "source-manifest.json").read_text())
for item in manifest["files"]:
    data = (a.root / item["path"]).read_bytes()
    if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Original source file mismatch: " + item["path"])
index = json.loads((a.root / "index.json").read_text())
for item in index["entries"]:
    lines = (a.root / item["path"]).read_text().splitlines()
    if item["line"] < 1 or item["line"] > len(lines) or item["anchor_text"] not in lines[item["line"] - 1]:
        raise ValueError("Index anchor does not match source: " + item["name"])
names = {item["name"] for item in index["entries"]}
for expected in ("Handle Invalidation", "TransformOpInterface", "SequenceOp", "NamedSequenceOp"):
    if expected not in names:
        raise ValueError("Expected official concept is missing from index: " + expected)
if not (a.root / "LICENSE.TXT").is_file() or not (a.root / "mlir/LICENSE.TXT").is_file():
    raise ValueError("LLVM license notices missing")
print(json.dumps({"status": "passed", "qualification": "offline_reference_material", "source_files": len(manifest["files"]), "index_entries": len(index["entries"]), "version": index["version"], "upstream_tool_executed": False}, sort_keys=True))
