#!/usr/bin/env python3
"""Check exact compressed upstream inputs without claiming a native build."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--prefix", type=Path, required=True)
p.add_argument("--manifest", type=Path, required=True)
a = p.parse_args()
lock = json.loads(a.manifest.read_text())
for row in lock["files"]:
    rel = PurePosixPath(row["path"])
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Unsafe material path")
    path = a.prefix / Path(*rel.parts)
    if not path.is_file() or path.is_symlink() or path.stat().st_size != row["bytes"]:
        raise ValueError("Missing or resized material: " + row["path"])
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    if h.hexdigest() != row["sha256"]:
        raise ValueError("Changed material: " + row["path"])
print(json.dumps({"status": "passed", "resource_id": lock["resource_id"], "verified_files": len(lock["files"]), "scope": "exact complete compressed upstream source plus original licenses; no source-build or tool execution qualification"}, sort_keys=True))
