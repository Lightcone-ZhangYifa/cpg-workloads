"""Verify a complete unpacked CPG worker delivery using its final inventory.

Use an externally obtained --expected-manifest-sha256 to bind the inventory.
Without one, this command checks internal consistency only. Unpack the ZIP
with a tool that preserves POSIX executable bits (for example, unzip).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root: Path, expected: str | None = None) -> dict:
    root = root.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("The bundle path and its ancestors must not be symlinks")
    manifest_path = root / "DELIVERY-MANIFEST.json"
    observed = sha(manifest_path)
    if expected is not None and observed != expected:
        raise ValueError("Delivery inventory differs from the external SHA-256")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = {}
    for row in manifest["files"]:
        relative = PurePosixPath(row["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != row["path"]:
            raise ValueError("Unsafe inventory path")
        if row["path"] in expected_files or row["path"] == "DELIVERY-MANIFEST.json":
            raise ValueError("Duplicate or self-referential inventory path")
        expected_files[row["path"]] = row
    actual_files = {}
    for path in root.rglob("*"):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Delivery files must be independent ordinary files: " + str(path))
        relative = path.relative_to(root).as_posix()
        if relative == "DELIVERY-MANIFEST.json":
            continue
        actual_files[relative] = path
    if set(actual_files) != set(expected_files):
        raise ValueError("Delivery file set differs from the inventory")
    for name, row in expected_files.items():
        path = actual_files[name]
        info = path.stat()
        if info.st_size != row["bytes"] or stat.S_IMODE(info.st_mode) != row["mode"] or sha(path) != row["sha256"]:
            raise ValueError("Delivery file bytes, permissions or hash differ: " + name)
    return {"status": "passed", "files": len(actual_files),
            "bytes": sum(x["bytes"] for x in expected_files.values()),
            "manifest_sha256": observed,
            "trust_scope": "external_manifest_bound" if expected else "internal_consistency_only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path.cwd())
    parser.add_argument("--expected-manifest-sha256")
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.bundle, arguments.expected_manifest_sha256), sort_keys=True))
