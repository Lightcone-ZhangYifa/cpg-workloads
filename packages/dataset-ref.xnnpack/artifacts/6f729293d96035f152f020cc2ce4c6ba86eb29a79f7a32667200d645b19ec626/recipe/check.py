#!/usr/bin/env python3
"""Verify the complete hydrated material, including all source notices and tests."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import pathlib
import stat

def snapshot(root):
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".cpg-prefix.json":
            continue
        info = path.lstat()
        row = {"path": relative, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISDIR(info.st_mode):
            row["kind"] = "directory"
        elif stat.S_ISLNK(info.st_mode):
            row.update(kind="symlink", target=os.readlink(path))
            path.resolve(strict=True).relative_to(root.resolve())
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise ValueError("Material file shares an install inode: " + relative)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            row.update(kind="file", bytes=info.st_size, sha256=digest)
        else:
            raise ValueError("Unsupported installed member: " + relative)
        rows.append(row)
    return rows

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", type=pathlib.Path, required=True)
    p.add_argument("--manifest", type=pathlib.Path, required=True)
    a = p.parse_args()
    expected = json.loads(a.manifest.read_text())
    before = {r["path"]: r for r in expected["files"]}
    actual = snapshot(a.prefix)
    after = {r["path"]: r for r in actual}
    if len(before) != len(expected["files"]) or len(after) != len(actual):
        raise ValueError("Duplicate material inventory path")
    if before != after:
        changed = [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
        raise ValueError("Material inventory mismatch: " + ", ".join(changed[:15]))
    print(json.dumps({"status": "passed", "resource_id": expected["resource_id"],
        "scope": expected["scope"], "file_count": sum(r["kind"] == "file" for r in actual),
        "directory_count": sum(r["kind"] == "directory" for r in actual),
        "lfs_object_count": expected["lfs_object_count"],
        "source_archive_sha256": expected["original_source"]["sha256"],
        "native_executed": False, "generator_executed": False,
        "official_benchmark_executed": False, "oci_executed": False}, sort_keys=True))

if __name__ == "__main__":
    main()
