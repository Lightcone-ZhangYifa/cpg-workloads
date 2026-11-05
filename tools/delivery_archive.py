"""Assemble one locked ZIP delivery on a temporary runner; never execute members."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

LIMIT = 2 * 1024 ** 3
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
BLOCK = 1024 * 1024


class AssemblyError(ValueError):
    pass


def _lock(value):
    if (not isinstance(value, dict) or type(value.get("bytes")) is not int
            or not 0 < value["bytes"] <= LIMIT
            or not isinstance(value.get("sha256"), str)
            or SHA256.fullmatch(value["sha256"]) is None):
        raise AssemblyError("Invalid bounded archive SHA256/size lock")
    return value["sha256"], value["bytes"]


def _relative(value, directory=False):
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise AssemblyError("Invalid ZIP member path")
    raw = value[:-1] if directory and value.endswith("/") else value
    if (raw.startswith("/") or re.match(r"^[A-Za-z]:", raw)
            or any(part in {"", ".", ".."} for part in raw.split("/"))
            or PurePosixPath(raw).as_posix() != raw):
        raise AssemblyError("Unsafe or noncanonical ZIP member path")
    return raw


def _ordinary_input(value, scratch):
    path = Path(value)
    if not path.is_absolute():
        raise AssemblyError("Delivery inputs must be absolute temporary paths")
    try:
        relative = path.relative_to(scratch)
    except ValueError:
        raise AssemblyError("Delivery input is outside its private scratch directory") from None
    if not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise AssemblyError("Invalid temporary input path")
    for node in (path, *path.parents):
        if node.is_symlink():
            raise AssemblyError("Temporary archive path contains a symlink")
        if node == scratch:
            break
    if not stat.S_ISREG(path.stat().st_mode):
        raise AssemblyError("Delivery input is not an ordinary file")
    return path


def _copy_verified(source, lock, target=None, aggregate=None):
    expected_sha, expected_size = _lock(lock)
    size, digest = 0, hashlib.sha256()
    with source.open("rb") as stream:
        while block := stream.read(BLOCK):
            size += len(block)
            if size > expected_size:
                raise AssemblyError("Input archive exceeds its size lock")
            digest.update(block)
            if aggregate is not None:
                aggregate.update(block)
            if target is not None:
                target.write(block)
    if size != expected_size or digest.hexdigest() != expected_sha:
        raise AssemblyError("Input archive differs from its SHA256/size lock")
    return size


def prepare(paths, input_specs, assembly, scratch):
    """Consume ordered, downloaded parts and return the one fully verified inner ZIP.

    Input paths and specs are parallel lists. The caller must use a private
    temporary directory and remains responsible for finally cleaning that
    directory. Only this function's temporary files and verified consumed input
    parts are removed. Failure never publishes anything.
    """
    if (not isinstance(paths, (list, tuple)) or not isinstance(input_specs, (list, tuple))
            or not 1 <= len(paths) <= 4 or len(paths) != len(input_specs)
            or not isinstance(assembly, dict)):
        raise AssemblyError("Expected one delivery assembled from one to four ordered inputs")
    scratch = Path(scratch)
    if not scratch.is_absolute() or scratch.is_symlink() or not scratch.is_dir():
        raise AssemblyError("Assembly scratch directory must be an existing private directory")
    if scratch.resolve() != scratch:
        raise AssemblyError("Assembly scratch path contains a symlink or noncanonical component")
    paths = [_ordinary_input(value, scratch) for value in paths]
    if len(set(paths)) != len(paths):
        raise AssemblyError("Duplicate temporary input path")
    outer_lock, member, delivery = assembly["archive"], assembly["member"], assembly["delivery"]
    outer_sha, outer_size = _lock(outer_lock)
    inner_sha, inner_size = _lock(member)
    if _lock(delivery) != (inner_sha, inner_size):
        raise AssemblyError("Inner archive differs from the publication delivery identity")
    member_name = _relative(member.get("path"))
    if not member_name.endswith(".zip"):
        raise AssemblyError("This delivery adapter only accepts an exact inner ZIP")
    if sum(_lock(spec)[1] for spec in input_specs) != outer_size:
        raise AssemblyError("Ordered part sizes do not match the complete outer archive")
    if any(path.stat().st_size != spec["bytes"] for path, spec in zip(paths, input_specs)):
        raise AssemblyError("Downloaded input size differs from its exact part lock")
    inner = scratch / ("inner-" + inner_sha + ".zip")
    outer = paths[0] if len(paths) == 1 else scratch / ("joined-" + outer_sha + ".zip")
    if inner.exists() or inner.is_symlink() or len(paths) > 1 and (outer.exists() or outer.is_symlink()):
        raise AssemblyError("Assembly output path already exists")
    complete = False
    created_outer = False
    try:
        if len(paths) == 1:
            if _lock(input_specs[0]) != (outer_sha, outer_size):
                raise AssemblyError("Single input differs from the complete outer archive lock")
            _copy_verified(outer, outer_lock)
        else:
            aggregate = hashlib.sha256()
            size = 0
            with outer.open("xb") as target:
                created_outer = True
                for path, spec in zip(paths, input_specs):
                    size += _copy_verified(path, spec, target, aggregate)
                    path.unlink()
            if size != outer_size or aggregate.hexdigest() != outer_sha:
                raise AssemblyError("Assembled outer archive differs from its full SHA256/size lock")
        with zipfile.ZipFile(outer) as archive:
            entries = archive.infolist()
            names = set()
            selected = None
            for entry in entries:
                name = _relative(entry.filename, entry.is_dir())
                if name in names:
                    raise AssemblyError("Duplicate ZIP member path")
                names.add(name)
                file_type = stat.S_IFMT(entry.external_attr >> 16)
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise AssemblyError("ZIP contains a symlink or special device member")
                if file_type == stat.S_IFDIR and not entry.is_dir():
                    raise AssemblyError("ZIP directory metadata and name disagree")
                if entry.filename == member_name:
                    selected = entry
            if (selected is None or selected.is_dir() or selected.flag_bits & 1
                    or stat.S_IFMT(selected.external_attr >> 16) not in (0, stat.S_IFREG)
                    or selected.file_size != inner_size):
                raise AssemblyError("Exact inner ZIP is missing or differs from its ordinary-file size lock")
            size, digest = 0, hashlib.sha256()
            with archive.open(selected) as source, inner.open("xb") as target:
                while block := source.read(BLOCK):
                    size += len(block)
                    if size > inner_size:
                        raise AssemblyError("Inner ZIP exceeds its size lock")
                    digest.update(block)
                    target.write(block)
            if size != inner_size or digest.hexdigest() != inner_sha:
                raise AssemblyError("Inner ZIP differs from its exact SHA256/size lock")
        outer.unlink()
        complete = True
        return inner
    finally:
        if not complete:
            if inner.is_file() and not inner.is_symlink():
                inner.unlink()
            if created_outer and outer.is_file() and not outer.is_symlink():
                outer.unlink()
