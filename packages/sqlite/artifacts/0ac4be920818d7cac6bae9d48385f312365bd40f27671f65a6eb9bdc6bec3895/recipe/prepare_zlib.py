"""Prepare the exact existing zlib development package for a private native build.

This is dpkg-deb extraction, not an APT installation or a package database change.
Only the verified static library, headers and notice are consumed by build.py.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--definition", required=True, type=Path)
    args = parser.parse_args()
    lock = json.loads(Path(__file__).with_name("zlib-lock.json").read_text())
    spec = json.loads(args.definition.read_text())
    if spec["id"] != lock["id"] or spec["version"] != lock["version"] or spec["sources"][0] != lock["source"]:
        raise RuntimeError("The active pinned zlib development definition changed; re-review this recipe")
    source = lock["source"]
    archive = args.cache.resolve() / "sha256" / source["sha256"][:2] / source["sha256"]
    if archive.is_symlink() or archive.stat().st_size != source["bytes"] or sha(archive) != source["sha256"]:
        raise RuntimeError("The exact existing zlib development download is absent or changed")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    commands = []
    def run(argv):
        result = subprocess.run([str(arg) for arg in argv], capture_output=True, text=True, timeout=60)
        commands.append({"argv": result.args, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise RuntimeError(json.dumps(commands[-1]))
        return result.stdout.strip()
    metadata = run(["dpkg-deb", "--field", archive, "Package", "Version", "Architecture"])
    for field in ("Package: zlib1g-dev", "Version: " + lock["version"], "Architecture: amd64"):
        if field not in metadata.splitlines():
            raise RuntimeError("Unexpected exact Debian package control metadata: " + metadata)
    run(["dpkg-deb", "--extract", archive, root / "extracted"])
    files = []
    for item in lock["files"]:
        path = root / "extracted" / item["path"]
        if path.is_symlink() or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise RuntimeError("The extracted locked zlib file differs: " + item["path"])
        files.append(item)
    receipt = {"status": "passed", "scope": "Exact Debian development archive plus private extraction of static library, headers and copyright notice; APT transaction not_run.",
               "id": lock["id"], "version": lock["version"], "source": source, "archive": str(archive),
               "files": files, "commands": commands, "apt_transaction": "not_run",
               "dependencies": {lock["id"]: {"prefix": str(root / "extracted"), "source": str(archive)}},
               "environment": {"CPG_SQLITE_ZLIB_ROOT": str(root / "extracted")}}
    (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
