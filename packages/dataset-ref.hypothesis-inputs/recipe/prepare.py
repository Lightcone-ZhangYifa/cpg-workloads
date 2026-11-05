#!/usr/bin/env python3
"""Prepare the complete fixed Hypothesis repository and all committed LFS files.

Uses the existing CPG acquisition, safe unpacking and material-package engine.
The original catalog definition is unchanged; previously unknown input identity
and the ten already committed LFS object identities are explicit supplements.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import shutil
import tarfile
import tempfile

from compiler_playground.resource_deploy import acquire_file, unpack_archive
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.archive import inventory
from compiler_playground.packages.spec import validate_spec

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def acquire(lock, cache, *, no_network, license_class, receipt):
    item = {"id": lock["id"], "source_url": lock["url"],
            "sha256": lock["sha256"], "archive_bytes": lock["bytes"],
            "license_class": license_class}
    if no_network:
        item["bundled_path"] = str(cache / "sha256" / lock["sha256"][:2] / lock["sha256"])
    return acquire_file(item, cache, receipt=receipt)

def assemble(raw, locks, cache, payload):
    main = locks["resolved_main_source"]
    if raw.is_symlink() or raw.stat().st_size != main["bytes"] or sha(raw) != main["sha256"]:
        raise ValueError("Original main archive identity mismatch")
    unpack_archive(raw, payload, strip_root=main["strip_root"])
    # CPG's secure TAR data filter removes group/other write bits. This fixed
    # archive has only ordinary files and directories; retain its reviewed
    # original 0664/0775 modes after the safe extraction and record them in the
    # full manifest. Git only records the executable bit, not these write bits.
    with tarfile.open(raw) as archive:
        for member in archive:
            parts = pathlib.PurePosixPath(member.name).parts[1:]
            if not parts:
                continue
            if not (member.isfile() or member.isdir()) or member.mode not in (0o664, 0o775):
                raise ValueError("Unexpected member type or mode in the exact original Hypothesis tar")
            target = payload.joinpath(*parts)
            if target.is_symlink() or not target.resolve().is_relative_to(payload.resolve()):
                raise ValueError("Unsafe original material mode restoration")
            target.chmod(member.mode)
    changed = []
    for lock in locks["lfs_objects"]:
        rel = pathlib.PurePosixPath(lock["path"])
        if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != lock["path"]:
            raise ValueError("Unsafe LFS destination")
        target = payload / rel
        if target.is_symlink() or not target.is_file() or not target.parent.resolve().is_relative_to(payload.resolve()):
            raise ValueError("LFS pointer is not an independent original file")
        if target.read_bytes() != lock["pointer"].encode("utf-8") or sha(target) != lock["pointer_sha256"]:
            raise ValueError("LFS pointer differs from the exact committed archive")
        obj = cache / "sha256" / lock["sha256"][:2] / lock["sha256"]
        if obj.is_symlink() or obj.stat().st_size != lock["bytes"] or sha(obj) != lock["sha256"]:
            raise ValueError("LFS object differs from the original pointer")
        mode = target.stat().st_mode & 0o777
        shutil.copyfile(obj, target)
        target.chmod(mode)
        if target.stat().st_nlink != 1 or target.stat().st_ino == obj.stat().st_ino:
            raise ValueError("Hydrated material must be an independent ordinary copy")
        changed.append(lock["path"])
    rows = inventory(payload)
    for row in rows:
        if row["kind"] == "file" and row["bytes"] <= 1024:
            if (payload / row["path"]).read_bytes().startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                raise ValueError("Unresolved Git LFS pointer remains: " + row["path"])
    return rows, changed

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--definition", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1] / "package.json")
    p.add_argument("--cache", type=pathlib.Path, required=True)
    p.add_argument("--output", type=pathlib.Path, required=True)
    p.add_argument("--no-network", action="store_true")
    a = p.parse_args()
    a.cache = a.cache.resolve()
    root = a.definition.resolve().parent
    spec = validate_spec(json.loads(a.definition.read_text()))
    locks = json.loads((root / "recipe/acquisition-locks.json").read_text())
    if spec["sources"] != locks["original_sources"]:
        raise ValueError("Canonical discovery sources changed")
    main_lock = locks["resolved_main_source"]
    original = spec["sources"][0]
    for key, value in original.items():
        if not (value is None and key in ("sha256", "bytes")) and main_lock[key] != value:
            raise ValueError("Supplemental acquisition lock replaced an original fact")
    receipts = []
    for lock in [main_lock] + locks["lfs_objects"]:
        receipt = {}
        acquire(lock, a.cache, no_network=a.no_network,
                license_class=spec["metadata"]["catalog"]["license_class"], receipt=receipt)
        receipts.append(receipt)
    raw = a.cache / "sha256" / main_lock["sha256"][:2] / main_lock["sha256"]
    with tempfile.TemporaryDirectory(prefix="cpg-hypothesis-material-") as temporary:
        payload = pathlib.Path(temporary) / "payload"
        rows, hydrated = assemble(raw, locks, a.cache, payload)
        expected = json.loads((root / "recipe/material-manifest.json").read_text())
        if rows != expected["files"]:
            raise ValueError("Prepared full material inventory differs from the frozen exact source closure")
        result = pack(spec, a.output, method="material", payload=payload, recipe_dir=root / "recipe",
                      provenance={"original_source_lock": main_lock,
                          "original_sources_unchanged": True,
                          "exact_git_tree_sha1": locks["exact_git_tree_sha1"],
                          "lfs_objects_hydrated": hydrated,
                          "qualification_scope": spec["recipe"]["qualification_scope"],
                          "native_execution_qualified": False,
                          "dataset_api_qualified": False})
    verify_package(a.output, expected_sha256=result["sha256"], expected_bytes=result["bytes"])
    print(json.dumps({"status": "passed", "artifact": result, "acquisitions": receipts}, indent=2))

if __name__ == "__main__":
    main()
