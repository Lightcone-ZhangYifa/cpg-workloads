#!/usr/bin/env python3
"""Explicit online preparation; fetch only immutable, hash-locked manifest inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--destination", type=Path, help="resource directory receiving assets; defaults beside recipe")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    destination = (args.destination or root).resolve()
    lock = json.loads((root / "source-lock.json").read_text())
    for item in lock["artifacts"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or not item["url"].startswith("https://"):
            raise ValueError("invalid locked path or URL")
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size == item["bytes"] and digest(path) == item["sha256"]:
            print(json.dumps({"path": str(path), "status": "verified_existing"}))
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                with urllib.request.urlopen(item["url"], timeout=60) as stream:
                    total = 0
                    while chunk := stream.read(256 * 1024):
                        total += len(chunk)
                        if total > item["bytes"]:
                            raise ValueError("download exceeds locked byte count")
                        output.write(chunk)
            if temporary.stat().st_size != item["bytes"] or digest(temporary) != item["sha256"]:
                raise ValueError("download size/SHA-256 does not match lock")
            temporary.replace(path)
            print(json.dumps({"path": str(path), "status": "acquired_verified"}))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
