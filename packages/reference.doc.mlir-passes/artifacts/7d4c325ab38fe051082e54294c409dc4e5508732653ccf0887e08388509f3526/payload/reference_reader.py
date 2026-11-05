#!/usr/bin/env python3
"""Read one independently installed, source-locked reference resource offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

TEXT_SUFFIXES = {".rst", ".md", ".td", ".h", ".hpp", ".cpp", ".c", ".txt"}
INDEX_KINDS = {"chapter", "literal_symbol", "declaration", "tablegen_definition", "pass", "operation"}


class IntegrityError(ValueError):
    """The reference resource differs from its declared source identity."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(raw: bytes):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise IntegrityError("Duplicate JSON key: " + key)
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


def relative(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise IntegrityError("Invalid relative path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != name or path == PurePosixPath("."):
        raise IntegrityError("Noncanonical relative path")
    return name


class ReferenceReader:
    """A reader for exactly one original reference entity and upstream version."""

    def __init__(self, root: str | Path, *, expected_inventory_sha256: str | None = None):
        self.root = Path(os.path.abspath(root))
        if any(path.is_symlink() for path in (self.root, *self.root.parents)) or not self.root.is_dir():
            raise IntegrityError("Reference root must be an ordinary directory")
        raw = self._read_file("inventory.json")
        self.inventory_sha256 = digest(raw)
        if expected_inventory_sha256 is not None and self.inventory_sha256 != expected_inventory_sha256:
            raise IntegrityError("Inventory differs from the independent package contract")
        self.anchored = expected_inventory_sha256 is not None
        self.inventory = load_json(raw)
        if self.inventory.get("schema_version") != 1:
            raise IntegrityError("Unsupported inventory schema")
        self.files = {}
        self.file_rows = {}
        for row in self.inventory["files"]:
            name = relative(row["path"])
            if name in self.files or name in {"inventory.json", ".cpg-prefix.json"}:
                raise IntegrityError("Duplicate or reserved inventory path")
            self.files[name] = self._read_file(name)
            self.file_rows[name] = row
        if not self.files:
            raise IntegrityError("Empty reference inventory")
        self._verify_disk()
        self.resource = load_json(self.files["resource.json"])
        self.entity_id = self.resource["id"]
        self.version = self.resource["version"]
        self.commit = self.resource["commit"]
        if not re.fullmatch(r"reference[.]doc[.][a-z0-9._-]+", self.entity_id):
            raise IntegrityError("Invalid reference entity identity")
        if not isinstance(self.version, str) or not self.version or not re.fullmatch(r"[0-9a-f]{40}", self.commit):
            raise IntegrityError("Reference version and commit must be exact")
        if self.inventory.get("resource_id") != self.entity_id:
            raise IntegrityError("Inventory belongs to another resource")
        lock = load_json(self.files["source-lock.json"])
        if (lock.get("resource_id"), lock.get("version"), lock.get("commit")) != (self.entity_id, self.version, self.commit):
            raise IntegrityError("Source lock belongs to another resource or version")
        self.sources = {}
        for row in lock["files"]:
            upstream = relative(row["upstream_path"])
            name = relative(row["path"])
            if upstream in self.sources or name != "materials/" + upstream or name not in self.files:
                raise IntegrityError("Duplicate, missing or misplaced source material")
            raw = self.files[name]
            git_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            locator = f"https://github.com/llvm/llvm-project/blob/{self.commit}/{upstream}"
            if (len(raw) != row["bytes"] or digest(raw) != row["sha256"]
                    or git_blob != row["git_blob_sha1"] or row["git_url"] != locator
                    or row["role"] not in {"reference", "license"}):
                raise IntegrityError("Source bytes or immutable identity differ: " + upstream)
            self.sources[upstream] = row
        if self.resource["primary_path"] not in self.sources:
            raise IntegrityError("Primary reference document is absent")
        self.include_edges = lock.get("include_edges", [])
        for edge in self.include_edges:
            if edge["from"] not in self.sources or edge["to"] not in self.sources:
                raise IntegrityError("Incomplete declared TableGen source closure")
            lines = self._text(edge["from"]).splitlines()
            if (type(edge["line"]) is not int or not 1 <= edge["line"] <= len(lines)
                    or not re.match(r'^[ \t]*include[ \t]+"' + re.escape(edge["include"]) + '"', lines[edge["line"] - 1])):
                raise IntegrityError("TableGen include edge differs from source")
        self.entries = [load_json(line) for line in self.files["indexes/entries.jsonl"].splitlines() if line]
        seen = set()
        for row in self.entries:
            source = self.sources.get(row["upstream_path"])
            if (row["entry_id"] in seen or row["entity_id"] != self.entity_id
                    or row["version"] != self.version or row["commit"] != self.commit
                    or row["kind"] not in INDEX_KINDS or source is None
                    or row["source_sha256"] != source["sha256"]):
                raise IntegrityError("Index identity differs from the selected resource")
            seen.add(row["entry_id"])
            lines = self._text(row["upstream_path"]).splitlines()
            if (type(row["line"]) is not int or type(row["end_line"]) is not int
                    or not 1 <= row["line"] <= row["end_line"] <= len(lines)
                    or row["text"] != lines[row["line"] - 1]):
                raise IntegrityError("Index location differs from the original source")

    def _read_file(self, name: str) -> bytes:
        path = self.root
        for part in PurePosixPath(relative(name)).parts:
            path = path / part
            if path.is_symlink():
                raise IntegrityError("Symlinks are not reference inputs")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise IntegrityError("Reference inputs must be independent ordinary files")
        return path.read_bytes()

    def _verify_disk(self) -> None:
        if digest(self._read_file("inventory.json")) != self.inventory_sha256:
            raise IntegrityError("Inventory changed after opening the resource")
        actual = set()
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            for name in dirs:
                if (Path(directory) / name).is_symlink():
                    raise IntegrityError("Reference tree contains a symlink directory")
            for name in names:
                path = Path(directory) / name
                key = path.relative_to(self.root).as_posix()
                raw = self._read_file(key)
                if key in {"inventory.json", ".cpg-prefix.json"}:
                    continue
                actual.add(key)
                row = self.file_rows.get(key)
                if (row is None or len(raw) != row["bytes"] or digest(raw) != row["sha256"]
                        or stat.S_IMODE(path.stat().st_mode) != row["mode"]):
                    raise IntegrityError("Reference file differs from inventory: " + key)
        if actual != set(self.files):
            raise IntegrityError("Reference file set differs from inventory")

    def _text(self, upstream: str) -> str:
        row = self.sources[upstream]
        if Path(upstream).suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError("Selected source is not a text document")
        return self.files[row["path"]].decode("utf-8")

    def _asset(self, asset: str | None) -> None:
        if asset is not None and asset != self.entity_id:
            raise ValueError("Asset is outside this independently installed resource")

    @staticmethod
    def _query(query: str, limit: int) -> None:
        if not isinstance(query, str) or not query.strip() or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Use a nonempty query and a limit between 1 and 1000")

    def verify(self) -> dict:
        self._verify_disk()
        return {"status": "passed", "entity_id": self.entity_id, "version": self.version,
                "commit": self.commit, "assets": 1, "source_files": len(self.sources),
                "payload_files": len(self.files) + 1, "index_entries": len(self.entries),
                "inventory_sha256": self.inventory_sha256,
                "integrity_mode": "externally_anchored" if self.anchored else "internal_consistency_only",
                "upstream_tool_functional": None, "official_benchmark": None, "dataset_verified": None}

    def search(self, query: str, *, asset: str | None = None, limit: int = 20) -> list[dict]:
        self._asset(asset)
        self._query(query, limit)
        self._verify_disk()
        hits = []
        for upstream, row in sorted(self.sources.items()):
            if row["role"] != "reference" or Path(upstream).suffix.lower() not in TEXT_SUFFIXES:
                continue
            for line, text in enumerate(self._text(upstream).splitlines(), 1):
                if query.casefold() in text.casefold():
                    hits.append({"entity_id": self.entity_id, "version": self.version, "commit": self.commit,
                                 "upstream_path": upstream, "line": line, "text": text,
                                 "source_sha256": row["sha256"], "source_url": row["git_url"] + f"#L{line}"})
                    if len(hits) >= limit:
                        return hits
        return hits

    def read(self, upstream_path: str, *, line: int = 1, count: int = 40) -> dict:
        relative(upstream_path)
        self._verify_disk()
        if upstream_path not in self.sources:
            raise ValueError("Path is outside this resource's source closure")
        lines = self._text(upstream_path).splitlines()
        if type(line) is not int or not 1 <= line <= len(lines) or type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("Invalid source line window")
        end = min(line + count - 1, len(lines))
        return {"entity_id": self.entity_id, "version": self.version, "commit": self.commit,
                "upstream_path": upstream_path, "line": line, "end_line": end,
                "lines": [{"line": number, "text": lines[number - 1]} for number in range(line, end + 1)],
                "source_sha256": self.sources[upstream_path]["sha256"]}

    def index(self, *, kind: str | None = None) -> list[dict]:
        self._verify_disk()
        if kind is not None and kind not in INDEX_KINDS:
            raise ValueError("Unknown reference index kind")
        return [dict(row) for row in self.entries if kind is None or row["kind"] == kind]

    def symbols(self, query: str, *, limit: int = 20) -> list[dict]:
        self._query(query, limit)
        return [row for row in self.index() if row["kind"] != "chapter" and query.casefold() in row["title"].casefold()][:limit]

    def passes(self, query: str, *, limit: int = 20) -> list[dict]:
        self._query(query, limit)
        return [row for row in self.index(kind="pass")
                if query.casefold() in (row["title"] + " " + row["pass_argument"]).casefold()][:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--expected-inventory-sha256")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("list")
    search = sub.add_parser("search")
    search.add_argument("query"); search.add_argument("--asset"); search.add_argument("--limit", type=int, default=20)
    read = sub.add_parser("read")
    read.add_argument("path"); read.add_argument("--line", type=int, default=1); read.add_argument("--count", type=int, default=40)
    index = sub.add_parser("index"); index.add_argument("--kind", choices=sorted(INDEX_KINDS))
    for name in ("symbols", "passes"):
        command = sub.add_parser(name); command.add_argument("query"); command.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    try:
        reader = ReferenceReader(args.root, expected_inventory_sha256=args.expected_inventory_sha256)
        if args.command == "verify": result = reader.verify()
        elif args.command == "list": result = [reader.resource]
        elif args.command == "search": result = reader.search(args.query, asset=args.asset, limit=args.limit)
        elif args.command == "read": result = reader.read(args.path, line=args.line, count=args.count)
        elif args.command == "index": result = reader.index(kind=args.kind)
        else: result = getattr(reader, args.command)(args.query, limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
