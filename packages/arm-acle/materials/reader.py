"""Read a pinned CPG documentation corpus without network access.

The index is a navigation aid, not a normative interpretation or a compiler.
Python 3.11+ and its SQLite FTS5 support are sufficient. No optional packages
are imported by this runtime reader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys

sys.dont_write_bytecode = True


def _safe(root: Path, relative: str) -> Path:
    p = PurePosixPath(relative)
    if p.is_absolute() or not p.parts or any(x in ("..", "") for x in p.parts):
        raise ValueError("expected a relative path inside the corpus")
    candidate = root.joinpath(*p.parts)
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("symlinks and paths outside the corpus are not supported")
    return candidate


class Corpus:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.metadata = json.loads((self.root / "metadata.json").read_text())
        self.files = {r["path"]: r for r in json.loads(
            (self.root / "source-lock.json").read_text())["files"]}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Literal whitespace-separated terms, ANDed; no SQL/FTS operators."""
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise ValueError("query must contain 1..512 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer in 1..100")
        terms = query.split()
        if not any(re.search(r"\w", x, re.UNICODE) for x in terms):
            raise ValueError("query contains no searchable characters")
        phrase = " AND ".join('"' + x.replace('"', '""') + '"' for x in terms)
        uri = (self.root / "search.sqlite").as_uri() + "?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT path,anchor,line_start,line_end,title,source_url,local_url,"
                "snippet(fts,7,'[',']',' … ',36) AS excerpt "
                "FROM fts WHERE fts MATCH ? ORDER BY bm25(fts),rowid LIMIT ?",
                (phrase, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def anchor(self, label: str) -> list[dict]:
        """Find an exact section anchor; labels remain scoped to source files."""
        return [r for r in json.loads((self.root / "anchors.json").read_text())
                if r["anchor"] == label]

    def read_source(self, path: str, start: int = 1, end: int | None = None,
                    external_root: str | Path | None = None) -> dict:
        """Read verified source lines; restricted bodies require a local import."""
        if path not in self.files:
            raise KeyError("source path is not in the pinned manifest")
        if (not isinstance(start, int) or isinstance(start, bool) or start < 1
                or (end is not None and (not isinstance(end, int)
                    or isinstance(end, bool) or end < start))):
            raise ValueError("invalid inclusive line range")
        end = min(start + 199, end) if end is not None else start + 199
        base = self.root if external_root is None else Path(external_root).resolve()
        source = _safe(base, path)
        if not source.is_file():
            raise FileNotFoundError("source body is not distributed; prepare it explicitly first")
        data = source.read_bytes()
        entry = self.files[path]
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("source integrity mismatch")
        lines = data.decode("utf-8").splitlines()
        return {"path": path, "sha256": entry["sha256"], "start": start,
                "end": min(end, len(lines)), "text": "\n".join(lines[start - 1:end]),
                "total_lines": len(lines)}

    def intrinsic(self, name: str) -> list[dict]:
        p = self.root / "intrinsics.jsonl"
        if not p.exists():
            return []
        return [r for line in p.read_text().splitlines()
                if (r := json.loads(line))["name"] == name]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    sub = ap.add_subparsers(dest="command", required=True)
    q = sub.add_parser("search"); q.add_argument("query"); q.add_argument("--limit", type=int, default=10)
    a = sub.add_parser("anchor"); a.add_argument("label")
    s = sub.add_parser("source"); s.add_argument("path"); s.add_argument("--start", type=int, default=1)
    s.add_argument("--end", type=int); s.add_argument("--external-root", type=Path)
    i = sub.add_parser("intrinsic"); i.add_argument("name")
    sub.add_parser("metadata")
    args = ap.parse_args(); c = Corpus(args.root)
    try:
        if args.command == "search": result = c.search(args.query, args.limit)
        elif args.command == "anchor": result = c.anchor(args.label)
        elif args.command == "source": result = c.read_source(args.path, args.start, args.end, args.external_root)
        elif args.command == "intrinsic": result = c.intrinsic(args.name)
        else: result = c.metadata
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, FileNotFoundError, UnicodeError, sqlite3.Error) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
