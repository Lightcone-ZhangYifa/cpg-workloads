"""Explicit, bounded download/import for pinned bodies omitted from a bundle.

Only this command can download. The normal corpus reader, verifier, installer
and checks are offline. Downloads never write into an installed corpus.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request


def check_bytes(data: bytes, entry: dict) -> None:
    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("download/import differs from pinned SHA256 or size: " + entry["path"])


def prepare(corpus: Path, destination: Path, paths: list[str] | None = None,
            import_root: Path | None = None, download: bool = False) -> list[dict]:
    corpus = corpus.resolve(); destination = destination.resolve()
    if destination.is_relative_to(corpus) or corpus.is_relative_to(destination):
        raise ValueError("external materials must be outside and not contain the corpus")
    if bool(import_root) == bool(download):
        raise ValueError("choose exactly one: --import-root or --download")
    entries = json.loads((corpus / "source-lock.json").read_text())["files"]
    known = {r["path"]: r for r in entries}
    chosen = list(known) if paths is None else paths
    if not chosen or len(chosen) != len(set(chosen)) or any(x not in known for x in chosen):
        raise ValueError("all selected paths must be unique pinned manifest entries")
    destination.mkdir(parents=True, exist_ok=True)
    out = []
    for name in chosen:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("unsafe manifest path")
        entry = known[name]; target = destination.joinpath(*p.parts)
        if target.is_symlink() or not target.resolve().is_relative_to(destination):
            raise ValueError("output path escapes destination")
        if target.exists():
            check_bytes(target.read_bytes(), entry)
            out.append({"path": name, "sha256": entry["sha256"], "status": "verified_existing"})
            continue
        if import_root is not None:
            source = import_root.resolve().joinpath(*p.parts)
            if source.is_symlink() or not source.resolve().is_relative_to(import_root.resolve()):
                raise ValueError("import path escapes input root")
            data = source.read_bytes()
        else:
            url = entry["url"]
            if not url.startswith("https://"):
                raise ValueError("download requires pinned HTTPS URL")
            request = urllib.request.Request(url, headers={"User-Agent": "CPG-reference_corpus-pinned-prepare"})
            with urllib.request.urlopen(request, timeout=60) as response:
                # Reject unexpectedly large or infinite responses before committing bytes.
                data = response.read(entry["bytes"] + 1)
        check_bytes(data, entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".cpg-", delete=False) as tmp:
            temporary = Path(tmp.name)
            tmp.write(data); tmp.flush(); os.fsync(tmp.fileno())
        try:
            # No clobber: a concurrent creator is not silently overwritten.
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        out.append({"path": name, "sha256": entry["sha256"], "status": "prepared"})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--destination", type=Path, required=True)
    ap.add_argument("--path", action="append", dest="paths")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--download", action="store_true")
    group.add_argument("--import-root", type=Path)
    args = ap.parse_args()
    result = prepare(args.corpus, args.destination, args.paths, args.import_root, args.download)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
