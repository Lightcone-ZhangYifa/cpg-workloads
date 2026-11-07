"""Read and verify one explicitly selected retained Megaparsec source operation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def plain(path):
    path = Path(path).expanduser()
    if ".." in path.parts:
        raise ValueError("Paths containing '..' are not accepted")
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("A selected path traverses a symlink")
    return path


def snapshot(root):
    rows = []
    for path in sorted(Path(root).rglob("*")):
        info = path.lstat()
        row = {"path": path.relative_to(root).as_posix(), "mode": stat.S_IMODE(info.st_mode)}
        if path.is_symlink():
            row.update(kind="symlink", target=os.readlink(path))
        elif path.is_file():
            row.update(kind="file", bytes=info.st_size, sha256=sha256(path))
        elif path.is_dir():
            row.update(kind="directory")
        else:
            raise ValueError("A source entry has an unsupported file type")
        rows.append(row)
    return rows


def source_runtime(build_dir):
    build = plain(build_dir)
    path = plain(build / "megaparsec-evidence/build-receipt.json")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if (receipt.get("status") != "passed" or receipt.get("resource_id") != "megaparsec"
            or receipt.get("version") != "9.8.3" or receipt.get("paths", {}).get("build") != str(build)):
        raise ValueError("Select a successfully completed, unmoved Megaparsec source operation")
    project = plain(receipt["project"])
    if not project.is_dir() or not project.is_relative_to(build):
        raise ValueError("The independent development project is absent; reinstall the source artifact")
    for name, expected in receipt["project_files"].items():
        target = plain(project / name)
        if not target.is_file() or sha256(target) != expected:
            raise ValueError("The locked offline project/config changed: " + name)
    for name, expected in receipt["project_source_inventories"].items():
        root = plain(project / name)
        if not root.is_dir() or not root.is_relative_to(project) or snapshot(root) != expected:
            raise ValueError("A source/replay input changed: " + name)
    toolchain = receipt["toolchain"]
    for name in ("ghc", "cabal"):
        tool = Path(toolchain[name])
        resolved = tool.resolve(strict=True)
        if not resolved.is_relative_to(build) or not resolved.is_file() or sha256(resolved) != toolchain[name + "_sha256"]:
            raise ValueError("The selected source operation's tool changed or was removed: " + name)
    for library in receipt["native_runtime_inputs"]:
        target = Path(library["path"])
        if not target.is_file() or sha256(target) != library["sha256"]:
            raise ValueError("The observed native runtime changed: " + library["name"])
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("LD_") and key not in {
                       "CABAL_CONFIG", "CABAL_DIR", "GHC_ENVIRONMENT", "GHC_PACKAGE_PATH", "LIBRARY_PATH"}}
    environment.update(receipt["replay_environment"])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PATH"] = os.pathsep.join((str(Path(toolchain["ghc"]).parent),
                                            str(Path(toolchain["cabal"]).parent),
                                            environment.get("PATH", os.defpath)))
    return build, project, receipt, environment
