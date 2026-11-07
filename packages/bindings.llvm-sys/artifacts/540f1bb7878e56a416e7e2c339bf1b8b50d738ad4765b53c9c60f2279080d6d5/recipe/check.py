"""Check a frozen reference-material tree, then exercise its local index."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def verify(root: Path, contract: dict) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("The installed prefix must be an ordinary directory")
    expected = {row["path"]: row for row in contract["files"]}
    observed = set()
    byte_count = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Unexpected symlink: " + relative)
        if stat.S_ISDIR(info.st_mode):
            continue
        if relative == ".cpg-prefix.json":
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Invalid manager ownership file")
            continue
        if not stat.S_ISREG(info.st_mode) or relative not in expected:
            raise ValueError("Unexpected installed entry: " + relative)
        row = expected[relative]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != row["sha256"] or info.st_size != row["bytes"]:
            raise ValueError("Material bytes changed: " + relative)
        if stat.S_IMODE(info.st_mode) != row["mode"]:
            raise ValueError("Material mode changed: " + relative)
        if info.st_nlink != 1:
            raise ValueError("Material is not an independent ordinary copy: " + relative)
        observed.add(relative)
        byte_count += info.st_size
    if observed != set(expected):
        raise ValueError("Missing installed files: " + repr(sorted(set(expected) - observed)))
    queries = []
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for query in contract.get("queries", []):
        command = [sys.executable, "-B", str(root / contract["entrypoint"]), *query["args"]]
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                                text=True, timeout=30, check=False)
        if result.returncode:
            raise ValueError("Local index query failed: " + result.stderr[-2000:])
        parsed = json.loads(result.stdout)
        if not parsed:
            raise ValueError("Local index query returned no evidence")
        queries.append({"asset": query.get("asset"), "args": query["args"],
                        "returncode": result.returncode, "output": parsed})
    return {"status": "passed", "scope": contract.get("scope", "reference material and local index only"),
            "files": len(observed), "bytes": byte_count, "queries": queries,
            "upstream_functional_qualification": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    print(json.dumps(verify(args.prefix.absolute(), contract), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
