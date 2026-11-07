#!/usr/bin/env python3
"""Verify every declared offline material, fail closed for missing/tampered bytes."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(root, manifest):
    root = Path(root).resolve()
    rows = json.loads(Path(manifest).read_text())["files"]
    seen = set()
    for row in rows:
        rel = Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts or str(rel) in seen:
            raise ValueError("Invalid or duplicate material path")
        seen.add(str(rel))
        p = root/rel
        if p.is_symlink() or not p.is_file() or root not in p.resolve().parents:
            raise ValueError("Missing or indirect material: " + str(rel))
        if p.stat().st_size != row["bytes"]:
            raise ValueError("Material byte count differs: " + str(rel))
        h = hashlib.sha256()
        with p.open("rb") as f:
            while block := f.read(1024*1024):
                h.update(block)
        if h.hexdigest() != row["sha256"]:
            raise ValueError("Material SHA256 differs: " + str(rel))
    return {"status": "passed", "verified_materials": len(rows),
            "functional_qualification": None}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("manifest")
    a = p.parse_args()
    print(json.dumps(verify(a.root, a.manifest), sort_keys=True))
