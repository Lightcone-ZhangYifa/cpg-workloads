#!/usr/bin/env python3
"""Check installed bytes and execute the installed Parsec-linked native programs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    share = prefix / "share/parsec"
    manifest = json.loads((share / "manifest.json").read_text())
    assert manifest["resource"] == "parsec" and manifest["version"] == "3.1.17.0"
    lock = json.loads((share / "source-lock.json").read_text())
    tar_hash = next(item["sha256"] for item in lock["files"] if item["path"] == "upstream/parsec-3.1.17.0.tar.gz")
    assert sha(share / "parsec-3.1.17.0.tar.gz") == tar_hash
    for row in manifest["files"]:
        path = prefix / row["path"]
        assert path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], row["path"]
    assert (share / "source/src/Text/Parsec.hs").is_file()
    assert (share / "licenses/Parsec-BSD-2-Clause.txt").read_bytes() == (share / "source/LICENSE").read_bytes()
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(prefix / "lib")
    output = subprocess.run([str(prefix / "bin/parsec-fixture")], capture_output=True, text=True, env=env, timeout=30, check=True)
    result = json.loads(output.stdout)
    assert result["parsec_version"] == "3.1.17.0" and result["total"] == result["passed"] == 27 and result["failed"] == 0
    regression = subprocess.run([str(prefix / "bin/upstream-issue127"), "1000000", "+RTS", "-M64m", "-RTS"],
                                capture_output=True, text=True, env=env, timeout=30, check=True)
    assert regression.stdout.strip() == "Right ()"
    print(json.dumps({"resource": "parsec", "version": "3.1.17.0", "status": "passed",
                      "scope": manifest["capability"], "fixture": result,
                      "source_sha256": tar_hash, "upstream_issue127": "passed",
                      "independent_prefix": str(prefix)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
