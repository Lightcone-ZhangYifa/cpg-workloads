#!/usr/bin/env python3
"""Read every installed source member; this does not build or execute its code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile


def inspect(path, root, module, file_count, logical_bytes):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Installed original archive is not an ordinary file")
    seen, count, total, contents = set(), 0, 0, {}
    inventory = hashlib.sha256()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            pure = PurePosixPath(member.name)
            if (pure.is_absolute() or ".." in pure.parts or "\\" in member.name
                    or not (member.name == root or member.name.startswith(root + "/"))
                    or member.name in seen or not (member.isdir() or member.isreg())
                    or member.issparse()):
                raise ValueError("Unexpected source archive member: " + member.name)
            seen.add(member.name)
            if not member.isreg():
                continue
            count += 1
            observed, digest = 0, hashlib.sha256()
            capture = member.name in {root + "/" + name for name in ("go.mod", "LICENSE", "README.md")}
            saved = bytearray()
            with archive.extractfile(member) as stream:
                while chunk := stream.read(1024 * 1024):
                    observed += len(chunk)
                    digest.update(chunk)
                    if capture:
                        if len(saved) + len(chunk) > 4 * 1024 * 1024:
                            raise ValueError("Unexpectedly large source metadata")
                        saved.extend(chunk)
            if observed != member.size:
                raise ValueError("Source member was not fully readable: " + member.name)
            total += observed
            entry = {"path": member.name, "bytes": observed, "sha256": digest.hexdigest()}
            inventory.update(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            if capture:
                contents[member.name.removeprefix(root + "/")] = bytes(saved)
    if count != file_count or total != logical_bytes:
        raise ValueError("Complete source read does not match the locked inventory")
    if set(contents) != {"go.mod", "LICENSE", "README.md"} or not all(contents.values()):
        raise ValueError("Source metadata is missing or empty")
    go_mod = contents["go.mod"].decode("utf-8")
    observed_module = re.search(r"(?m)^module\s+(\S+)\s*$", go_mod)
    go = re.search(r"(?m)^go\s+(\S+)\s*$", go_mod)
    if observed_module is None or observed_module.group(1) != module or go is None:
        raise ValueError("Root Go module metadata is not the expected original project")
    if b"Apache License" not in contents["LICENSE"] or b"Version 2.0" not in contents["LICENSE"]:
        raise ValueError("Expected original Apache-2.0 notice is absent")
    return {"status": "passed", "scope": "installed_static_source_material_read_only",
            "ordinary_files_read": count, "logical_bytes_read": total,
            "content_inventory_sha256": inventory.hexdigest(), "go_module": module,
            "declared_go_version": go.group(1),
            "metadata_read": {key: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                              for key, value in contents.items()},
            "native_build_qualified": False, "native_execution_qualified": False,
            "go_dependencies_acquired": False, "formal_benchmark_qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--relative", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--files", type=int, required=True)
    parser.add_argument("--bytes", type=int, required=True)
    args = parser.parse_args()
    try:
        relative = PurePosixPath(args.relative)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != args.relative:
            raise ValueError("Unsafe installed archive path")
        result = inspect(args.prefix / relative, args.root, args.module, args.files, args.bytes)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "reason": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
