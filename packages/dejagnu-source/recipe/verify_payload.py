#!/usr/bin/env python3
"""Offline verification of the complete, unmodified DejaGNU reference payload."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

RAW_SHA256 = "87daefacd7958b4a69f88c6856dbd1634261963c414079d0c371f589cd66a2e3"
RAW_BYTES = 622059


def verify(root: Path) -> dict:
    raw = root / "original-inputs/dejagnu-1.6.3.tar.gz"
    source = root / "sources/dejagnu"
    if raw.is_symlink() or not raw.is_file():
        raise ValueError("original archive must be an ordinary file")
    data = raw.read_bytes()
    if len(data) != RAW_BYTES or hashlib.sha256(data).hexdigest() != RAW_SHA256:
        raise ValueError("original archive identity mismatch")
    expected = set()
    logical_bytes = 0
    with tarfile.open(raw, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] != "dejagnu-1.6.3":
                raise ValueError("unsafe source path")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("unexpected non-regular source entry")
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if relative in expected:
                raise ValueError("duplicate source entry")
            expected.add(relative)
            installed = source / relative
            if installed.is_symlink() or not installed.is_file():
                raise ValueError("source missing or symlinked: " + relative)
            original = archive.extractfile(member).read()
            if installed.read_bytes() != original:
                raise ValueError("source changed: " + relative)
            logical_bytes += len(original)
    actual = {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("source file inventory differs from original")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("source tree contains a symlink")
    for required in ("COPYING", "doc/fdl.texi", "doc/dejagnu.texi", "lib/framework.exp",
                     "runtest.exp", "baseboards/unix.exp", "commands/report-card.awk"):
        if required not in expected:
            raise ValueError("missing material component: " + required)
    return {"status": "passed", "resource_id": "dejagnu-source", "version": "1.6.3",
            "archive_sha256": RAW_SHA256, "archive_bytes": RAW_BYTES,
            "source_files": len(expected), "source_logical_bytes": logical_bytes,
            "source_material_only": True, "runnable_harness_qualified": False,
            "gcc_regression_executed": False, "network_used": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.payload), ensure_ascii=False, indent=2))
