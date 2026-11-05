#!/usr/bin/env python3
"""Check every installed upstream material member without executing corpus code."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def snapshot(root):
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".cpg-prefix.json":
            continue
        mode = path.lstat().st_mode
        row = {"path": relative, "mode": stat.S_IMODE(mode)}
        if stat.S_ISLNK(mode):
            row.update(kind="symlink", target=os.readlink(path))
        elif stat.S_ISDIR(mode):
            row.update(kind="directory")
        elif stat.S_ISREG(mode):
            with path.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            row.update(kind="file", bytes=path.stat().st_size, sha256=checksum)
        else:
            raise ValueError("Unexpected material member: " + relative)
        rows.append(row)
    return sorted(rows, key=lambda row: row["path"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.manifest.read_text())
    actual = snapshot(args.prefix)
    if actual != expected["files"]:
        before = {row["path"]: row for row in expected["files"]}
        after = {row["path"]: row for row in actual}
        changed = [name for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
        raise ValueError("Complete material inventory differs: " + ", ".join(changed[:10]))
    print(json.dumps({"status": "passed", "resource_id": expected["resource_id"],
        "qualification": expected["qualification"],
        "source_archive": expected["source_archive"],
        "files": sum(row["kind"] == "file" for row in actual),
        "symlinks": sum(row["kind"] == "symlink" for row in actual),
        "bytes": sum(row.get("bytes", 0) for row in actual),
        "upstream_programs_executed": 0, "benchmark_score_granted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
