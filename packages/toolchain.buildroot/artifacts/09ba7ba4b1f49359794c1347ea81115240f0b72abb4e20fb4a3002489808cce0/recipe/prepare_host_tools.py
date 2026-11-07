#!/usr/bin/env python3
"""Verify and unpack explicit Ubuntu build aids into an independent prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def prepare(materials, prefix, names=None):
    materials, prefix = Path(materials).resolve(), Path(prefix).resolve()
    lock = json.loads((materials / "host-input-lock.json").read_text())
    rows = [row for row in lock["packages"] if names is None or row["name"] in names]
    if names is not None and {row["name"] for row in rows} != set(names):
        raise ValueError("Host input lock does not cover requested tools")
    prefix.mkdir(parents=True, exist_ok=True)
    for row in rows:
        archive = materials / row["file"]
        if archive.stat().st_size != row["bytes"]:
            raise ValueError("Host package size mismatch: " + row["name"])
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                raise ValueError("Host package digest mismatch: " + row["name"])
        subprocess.run(["dpkg-deb", "-x", str(archive), str(prefix)], check=True)
    # Keep nonstandard-prefix dependencies private without exporting
    # LD_LIBRARY_PATH (which ct-ng deliberately rejects).
    for name in ("gawk", "rsync"):
        program = prefix / "usr/bin" / name
        if not program.exists():
            continue
        original = program.with_name(name + ".real")
        program.rename(original)
        program.write_text('#!/bin/sh\n'
                           'self=$(readlink -f -- "$0")\n'
                           'bin=$(CDPATH= cd -- "$(dirname -- "$self")" && pwd)\n'
                           'exec /lib64/ld-linux-x86-64.so.2 --library-path '
                           '"$bin/../lib/x86_64-linux-gnu" "$bin/' + name + '.real" "$@"\n')
        program.chmod(0o755)
    return {"status": "prepared", "packages": [row["name"] for row in rows],
            "system_package_manager_modified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("materials")
    parser.add_argument("prefix")
    parser.add_argument("--names", nargs="+")
    args = parser.parse_args()
    print(json.dumps(prepare(args.materials, args.prefix, args.names)))
