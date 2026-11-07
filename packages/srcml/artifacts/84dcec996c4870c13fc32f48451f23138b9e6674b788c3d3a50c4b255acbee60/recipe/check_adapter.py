#!/usr/bin/env python3
"""Protected recipe hook: verify installed bytes, then run one offline check.

CPG v0.21.14 verifies recipe/tools before invoking hooks; installed payload
verification is otherwise an explicit API call. This hook makes the check
contract fail closed without modifying or bypassing that original engine.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid


def inventory(root):
    rows = []
    for directory, subdirs, files in os.walk(root, followlinks=False):
        for name in sorted(subdirs + files):
            p = Path(directory) / name
            relative = p.relative_to(root).as_posix()
            if relative == ".cpg-prefix.json":
                continue  # Manager-owned prefix identity, not upstream payload.
            info = p.lstat()
            row = {"path": relative, "mode": stat.S_IMODE(info.st_mode) & 0o777}
            if stat.S_ISREG(info.st_mode):
                with p.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                row.update(kind="file", bytes=info.st_size, sha256=digest)
            elif stat.S_ISDIR(info.st_mode):
                row.update(kind="directory")
            elif stat.S_ISLNK(info.st_mode):
                if not p.resolve(strict=True).is_relative_to(root):
                    raise ValueError("Escaping payload symlink: " + relative)
                row.update(kind="symlink", target=os.readlink(p))
            else:
                raise ValueError("Unsupported installed entry: " + relative)
            rows.append(row)
        subdirs[:] = sorted(name for name in subdirs if not (Path(directory) / name).is_symlink())
    return sorted(rows, key=lambda row: row["path"])


def main():
    prefix, resource, build, mode = sys.argv[1:]
    root = Path(prefix).resolve(strict=True)
    lock = json.loads((Path(__file__).resolve().parent / "payload-lock.json").read_text())
    try:
        if inventory(root) != lock["files"]:
            raise ValueError("Installed payload differs from recipe-bound file inventory")
    except (OSError, ValueError) as error:
        print(json.dumps({"resource": resource, "status": "rejected", "stage": "payload-integrity",
                          "reason": str(error), "tool_started": False}), flush=True)
        return 2
    if mode == "version":
        command = [x.replace("{prefix}", str(root)) for x in lock["version_argv"]]
    elif mode == "functional":
        output = Path(build) / "validation" / uuid.uuid4().hex
        command = [sys.executable, "-B", str(root / "native_checks.py"), resource,
                   "--output", str(output)]
    else:
        raise ValueError("Unknown check mode")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
