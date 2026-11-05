#!/usr/bin/env python3
"""Verify all exact declared MBPP files, Git blobs and the complete subtree hash."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import stat

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    a = p.parse_args()
    expected = json.loads(a.manifest.read_text())
    actual = []
    for path in sorted(a.prefix.rglob("*")):
        name = path.relative_to(a.prefix).as_posix()
        if name == ".cpg-prefix.json":
            continue
        info = path.lstat()
        row = {"path": name, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISDIR(info.st_mode):
            row["kind"] = "directory"
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise ValueError("MBPP files must be ordinary independent copies")
            data = path.read_bytes()
            row.update(kind="file", bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        else:
            raise ValueError("Unexpected MBPP source member type")
        actual.append(row)
    if actual != expected["files"]:
        raise ValueError("Complete MBPP subtree file set, bytes or modes changed")
    files = expected["source_materials"]["files"]
    tree_rows = []
    for source in files:
        data = (a.prefix / source["path"]).read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if digest != source["git_blob_sha1"]:
            raise ValueError("Original MBPP Git blob identity changed")
        if source["path"].startswith("mbpp/"):
            tree_rows.append((Path(source["path"]).name, digest))
    tree_rows.sort(key=lambda item: item[0].encode())
    tree = b"".join(b"100644 " + name.encode() + b"\0" + bytes.fromhex(digest) for name, digest in tree_rows)
    tree_sha1 = hashlib.sha1(b"tree " + str(len(tree)).encode() + b"\0" + tree).hexdigest()
    if tree_sha1 != expected["source_materials"]["subtree_git_tree_sha1"]:
        raise ValueError("The complete original MBPP subtree Git tree changed")
    print(json.dumps({"status": "passed", "resource_id": expected["resource_id"], "file_count": 4,
        "mbpp_subtree_git_sha1": tree_sha1, "execution_category": "declared_mbpp_subtree_material_only",
        "monorepo_not_acquired": True, "native_execution": False, "dataset_qualification_increment": 0}, sort_keys=True))

if __name__ == "__main__":
    main()
