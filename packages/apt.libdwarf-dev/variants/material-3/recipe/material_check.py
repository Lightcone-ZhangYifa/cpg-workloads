#!/usr/bin/env python3
"""Check the complete installed material inventory without executing its contents."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def snapshot(root):
    root = Path(root).absolute()
    rows = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            p = Path(directory) / name
            rel = p.relative_to(root).as_posix()
            if rel == ".cpg-prefix.json":
                continue
            st = p.lstat()
            row = {"path": rel, "mode": stat.S_IMODE(st.st_mode)}
            if stat.S_ISLNK(st.st_mode):
                target = os.readlink(p)
                if os.path.isabs(target) or not p.resolve(strict=True).is_relative_to(root):
                    raise ValueError(f"Unconfined symlink: {rel}")
                row.update(kind="symlink", target=target)
            elif stat.S_ISDIR(st.st_mode):
                row.update(kind="directory")
            elif stat.S_ISREG(st.st_mode):
                h = hashlib.sha256()
                with p.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(block)
                row.update(kind="file", bytes=st.st_size, sha256=h.hexdigest())
            else:
                raise ValueError(f"Unsupported file type: {rel}")
            rows.append(row)
    return sorted(rows, key=lambda r: r["path"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    wanted = json.loads(args.manifest.read_text())
    actual = snapshot(args.prefix)
    if actual != wanted["files"]:
        expected_by_path = {row["path"]: row for row in wanted["files"]}
        actual_by_path = {row["path"]: row for row in actual}
        changed = [p for p in sorted(set(expected_by_path) | set(actual_by_path))
                   if expected_by_path.get(p) != actual_by_path.get(p)]
        raise ValueError("Material inventory mismatch: " + json.dumps(changed[:30]))
    print(json.dumps({"status": "passed", "scope": "declared material integrity only",
                      "files": sum(row["kind"] == "file" for row in actual),
                      "functional_execution": False}, sort_keys=True))


if __name__ == "__main__":
    main()
