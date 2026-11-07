#!/usr/bin/env python3
"""Original-CPG recipe hook: bind material and external SDK before execution.

The original engine protects recipe/tools. This recipe additionally checks the
installed payload and the fixed, external SDK without modifying the core API.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid


def inventory(root, ignored=()):
    root = Path(root).resolve(strict=True)
    rows = []
    ignored = set(ignored)
    for directory, subdirs, files in os.walk(root, followlinks=False):
        for name in sorted(subdirs + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative in ignored or any(relative.startswith(x + "/") for x in ignored):
                continue
            info = path.lstat()
            row = {"path": relative, "mode": stat.S_IMODE(info.st_mode) & 0o777}
            if stat.S_ISREG(info.st_mode):
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                row.update(kind="file", bytes=info.st_size, sha256=digest)
            elif stat.S_ISDIR(info.st_mode):
                row["kind"] = "directory"
            elif stat.S_ISLNK(info.st_mode):
                if not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError("Escaping symlink: " + relative)
                row.update(kind="symlink", target=os.readlink(path))
            else:
                raise ValueError("Unsupported file type: " + relative)
            rows.append(row)
        subdirs[:] = sorted(name for name in subdirs
                            if not (Path(directory) / name).is_symlink()
                            and (Path(directory) / name).relative_to(root).as_posix() not in ignored)
    return sorted(rows, key=lambda row: row["path"])


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    prefix, resource, build, mode = sys.argv[1:]
    recipe = Path(__file__).resolve().parent
    lock = json.loads((recipe / "payload-lock.json").read_text())
    stage = "payload-integrity"
    try:
        root = Path(prefix).resolve(strict=True)
        if resource != lock["resource"]:
            raise ValueError("Resource differs from protected recipe identity")
        if inventory(root, [".cpg-prefix.json"]) != lock["files"]:
            raise ValueError("Installed payload differs from protected recipe inventory")
        stage = "external-sdk-integrity"
        sdk_lock_path = recipe / "sdk-binding.json"
        sdk_lock = json.loads(sdk_lock_path.read_text())
        selected = os.environ.get(sdk_lock["environment"])
        if not selected:
            raise ValueError("Set " + sdk_lock["environment"] + " to the separately prepared fixed SDK")
        sdk = Path(selected).absolute()
        for part in [sdk, *sdk.parents]:
            if part.is_symlink():
                raise ValueError("SDK path may not contain symbolic links")
        if inventory(sdk, sdk_lock["ignored_paths"]) != sdk_lock["files"]:
            raise ValueError("External SDK does not match the fixed offline SDK inventory")
        binding = {"root": str(sdk), "environment": sdk_lock["environment"],
                   "version": sdk_lock["version"], "lock_sha256": sha(sdk_lock_path),
                   "verified_files": sum(x["kind"] == "file" for x in sdk_lock["files"]),
                   "verified_bytes": sum(x.get("bytes", 0) for x in sdk_lock["files"]),
                   "ignored_paths": sdk_lock["ignored_paths"]}
    except (KeyError, OSError, ValueError) as error:
        print(json.dumps({"resource": resource, "status": "rejected", "stage": stage,
                          "reason": str(error), "tool_started": False}), flush=True)
        return 2
    if mode == "version":
        command = [str(sdk / x) if i == 0 else x for i, x in enumerate(sdk_lock["version_argv"])]
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if completed.returncode or sdk_lock["expected_version_text"] not in completed.stdout:
            print(json.dumps({"resource": resource, "status": "failed", "stage": "sdk-version",
                              "returncode": completed.returncode, "output": completed.stdout}), flush=True)
            return 3
        print(json.dumps({"resource": resource, "version": lock["version"], "status": "passed",
                          "identity_basis": "protected material and upstream dependency lock",
                          "sdk": binding, "sdk_version_output": completed.stdout}), flush=True)
        return 0
    if mode != "functional":
        raise ValueError("Unknown check mode: " + mode)
    output = Path(build).absolute() / "validation" / uuid.uuid4().hex
    if output == root or root in output.parents or output == sdk or sdk in output.parents:
        raise ValueError("Validation output must not be inside an installed prefix")
    command = [sys.executable, "-B", str(root / "run_offline.py"),
               "--sdk-root", str(sdk), "--output", str(output)]
    result = subprocess.run(command, check=False)
    if output.exists():
        (output / "cpg-sdk-binding.json").write_text(json.dumps(binding, indent=2) + "\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
