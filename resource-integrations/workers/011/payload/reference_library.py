#!/usr/bin/env python3
"""Read and search the fixed worker 011 LLVM reference materials offline.

This module contains no downloader. Pass an externally trusted inventory hash
when consuming a bundle from an untrusted path. Hash checks prove byte identity,
not compiler correctness or upstream code execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

COMMIT = "87f0227cb60147a26a1eeb4fb06e3b505e9c7261"
ASSET_IDS = (
    "reference.doc.openmp-opt", "reference.doc.llvm-remarks",
    "reference.doc.llvm-testsuite", "reference.doc.mlir-sparse",
)
ALLOWED_MANAGER_FILES = {".cpg-prefix.json"}


class IntegrityError(ValueError):
    """The explicit local reference inventory or source closure is invalid."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _json(b: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise IntegrityError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(b, object_pairs_hook=pairs)


def _relative(s: str) -> str:
    if not isinstance(s, str) or not s or "\\" in s or "\0" in s:
        raise IntegrityError("invalid relative path")
    p = PurePosixPath(s)
    if p.is_absolute() or any(x in (".", "..") for x in p.parts) or str(p) != s:
        raise IntegrityError(f"unsafe relative path: {s}")
    return s


class ReferenceLibrary:
    """Verified in-memory view of four bounded LLVM documentation assets."""

    def __init__(self, root: str | Path, *, expected_inventory_sha256: str | None = None):
        self.root = Path(os.path.abspath(os.fspath(root)))
        for parent in [self.root, *self.root.parents]:
            if parent.is_symlink():
                raise IntegrityError(f"symlink in root ancestry: {parent}")
        if not self.root.is_dir():
            raise IntegrityError("reference root is not a directory")
        raw = self._read("inventory.json")
        self.inventory_sha256 = _sha(raw)
        if expected_inventory_sha256 is not None and self.inventory_sha256 != expected_inventory_sha256:
            raise IntegrityError("inventory SHA-256 differs from the caller's trusted identity")
        inventory = _json(raw)
        if inventory.get("schema_version") != 1 or inventory.get("commit") != COMMIT:
            raise IntegrityError("unsupported inventory version or upstream commit")
        self._files: dict[str, bytes] = {}
        rows = inventory.get("files")
        if not isinstance(rows, list) or not rows:
            raise IntegrityError("empty or invalid inventory")
        for row in rows:
            name = _relative(row["path"])
            if name == "inventory.json" or name in self._files:
                raise IntegrityError(f"duplicate or self-referential inventory entry: {name}")
            b = self._read(name)
            if len(b) != row["bytes"] or _sha(b) != row["sha256"]:
                raise IntegrityError(f"file bytes differ from inventory: {name}")
            self._files[name] = b
        actual: set[str] = set()
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            for d in dirs:
                if (Path(directory) / d).is_symlink():
                    raise IntegrityError("symlink directory inside reference root")
            for n in names:
                p = Path(directory) / n
                rel = p.relative_to(self.root).as_posix()
                if rel in ALLOWED_MANAGER_FILES:
                    # PackageManager owns this exact top-level state file. It
                    # cannot exempt any upstream or index path from validation.
                    self._read(rel)
                    continue
                self._read(rel)
                actual.add(rel)
        if actual != set(self._files) | {"inventory.json"}:
            raise IntegrityError("reference file set differs from the explicit inventory")
        self.assets = _json(self._files["assets.json"])
        if sorted(x["entity_id"] for x in self.assets) != sorted(ASSET_IDS):
            raise IntegrityError("asset IDs differ from the assigned worker scope")
        self.sources = _json(self._files["materials/source-manifest.json"])
        if self.sources.get("commit") != COMMIT or self.sources.get("tag") != "llvmorg-20.1.8":
            raise IntegrityError("source pin differs from the fixed reference release")
        for evidence_key in ("commit_evidence", "tag_evidence"):
            evidence = self.sources[evidence_key]
            evidence_bytes = self._files[_relative(evidence["path"])]
            if _sha(evidence_bytes) != evidence["sha256"] or _json(evidence_bytes[4:]).get("commit") != COMMIT:
                raise IntegrityError("tag/commit provenance disagrees with the fixed source pin")
        source_rows = self.sources["files"]
        self.by_source: dict[str, dict] = {}
        for row in source_rows:
            path = _relative(row["path"])
            upstream = _relative(row["upstream_path"])
            if upstream in self.by_source or path not in self._files:
                raise IntegrityError("duplicate or missing upstream source")
            b = self._files[path]
            git_hash = hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()
            if len(b) != row["bytes"] or _sha(b) != row["sha256"] or git_hash != row["git_blob_sha1"]:
                raise IntegrityError(f"source identity mismatch: {upstream}")
            self.by_source[upstream] = row
        for edge in self.sources["tablegen_include_edges"]:
            if edge["from"] not in self.by_source or edge["to"] not in self.by_source:
                raise IntegrityError("incomplete TableGen include closure")
            line = self._text(edge["from"]).splitlines()[edge["line"] - 1]
            if not re.match(r'^\s*include\s+"' + re.escape(edge["include"]) + '"', line):
                raise IntegrityError("TableGen include edge disagrees with source text")
        self.index = [_json(line.encode()) for line in self._files["indexes/entries.jsonl"].decode().splitlines() if line]
        seen: set[str] = set()
        for row in self.index:
            if row["entry_id"] in seen or row["asset_id"] not in ASSET_IDS:
                raise IntegrityError("duplicate index key or unknown asset")
            seen.add(row["entry_id"])
            source = self.by_source.get(row["upstream_path"])
            if source is None or source["sha256"] != row["source_sha256"]:
                raise IntegrityError("index references an unbound source")
            lines = self._text(row["upstream_path"]).splitlines()
            if not (1 <= row["line"] <= row["end_line"] <= len(lines)):
                raise IntegrityError("index line range exceeds source")

    def _read(self, relative: str) -> bytes:
        _relative(relative)
        p = self.root
        for part in PurePosixPath(relative).parts:
            p = p / part
            if p.is_symlink():
                raise IntegrityError(f"symlink is forbidden: {relative}")
        try:
            info = p.stat()
        except OSError as e:
            raise IntegrityError(f"missing local file: {relative}") from e
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise IntegrityError(f"expected an independent ordinary file: {relative}")
        return p.read_bytes()

    def _text(self, upstream: str) -> str:
        return self._files[self.by_source[upstream]["path"]].decode("utf-8")

    def verify(self) -> dict:
        return {
            "status": "passed", "inventory_sha256": self.inventory_sha256,
            "commit": COMMIT, "assets": len(self.assets),
            "upstream_files": len(self.by_source),
            "upstream_bytes": sum(x["bytes"] for x in self.by_source.values()),
            "index_entries": len(self.index),
            "tablegen_include_edges": len(self.sources["tablegen_include_edges"]),
            "scope": "reference material and local retrieval only",
            "tool_functional": None, "dataset_verified": None,
            "official_benchmark": None,
        }

    def chapters(self, asset_id: str | None = None) -> list[dict]:
        self._asset(asset_id)
        return [dict(x) for x in self.index if asset_id is None or x["asset_id"] == asset_id]

    def _asset(self, asset_id: str | None) -> None:
        if asset_id is not None and asset_id not in ASSET_IDS:
            raise ValueError(f"unknown asset ID: {asset_id}")

    def search(self, query: str, *, asset_id: str | None = None, limit: int = 20) -> list[dict]:
        self._asset(asset_id)
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        needle = query.casefold()
        matches = []
        for upstream, source in sorted(self.by_source.items()):
            ids = source["asset_ids"]
            if not ids or (asset_id is not None and asset_id not in ids):
                continue
            for lineno, line in enumerate(self._text(upstream).splitlines(), 1):
                if needle in line.casefold():
                    matches.append({
                        "asset_ids": list(ids), "upstream_path": upstream,
                        "line": lineno, "text": line,
                        "source_sha256": source["sha256"],
                        "source_url": source["git_url"] + f"#L{lineno}",
                    })
                    if len(matches) >= limit:
                        return matches
        return matches

    def read(self, upstream_path: str, *, line: int = 1, count: int = 40) -> dict:
        _relative(upstream_path)
        if upstream_path not in self.by_source:
            raise ValueError("path is outside the declared upstream material set")
        lines = self._text(upstream_path).splitlines()
        if not isinstance(line, int) or line < 1 or line > len(lines):
            raise ValueError("line is outside the source")
        if not isinstance(count, int) or not 1 <= count <= 500:
            raise ValueError("count must be between 1 and 500")
        last = min(line + count - 1, len(lines))
        return {"upstream_path": upstream_path, "line": line, "end_line": last,
                "lines": [{"line": i, "text": lines[i - 1]} for i in range(line, last + 1)],
                "source_sha256": self.by_source[upstream_path]["sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--expected-inventory-sha256")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("list")
    sections = sub.add_parser("chapters")
    sections.add_argument("--asset")
    query = sub.add_parser("search")
    query.add_argument("query")
    query.add_argument("--asset")
    query.add_argument("--limit", type=int, default=20)
    reader = sub.add_parser("read")
    reader.add_argument("path")
    reader.add_argument("--line", type=int, default=1)
    reader.add_argument("--count", type=int, default=40)
    args = parser.parse_args()
    try:
        lib = ReferenceLibrary(args.root, expected_inventory_sha256=args.expected_inventory_sha256)
        if args.command == "verify":
            result = lib.verify()
        elif args.command == "list":
            result = lib.assets
        elif args.command == "chapters":
            result = lib.chapters(args.asset)
        elif args.command == "search":
            result = lib.search(args.query, asset_id=args.asset, limit=args.limit)
        else:
            result = lib.read(args.path, line=args.line, count=args.count)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (IntegrityError, ValueError, OSError, KeyError) as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
