"""Internal persistence primitives; no network or repository-root assumptions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path: str | Path) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=invalid)


def atomic_json(path: str | Path, value: Any) -> None:
    """Publish one complete JSON value on a local POSIX filesystem.

    Serialize before touching the destination. Each writer owns its temporary
    file, so a stale file or another writer cannot truncate its data. This is
    atomic replacement, not a compare-and-swap or a distributed transaction.
    Existing regular-file permissions are retained; new files are private.
    A directory fsync error after replacement means durability is unconfirmed.
    """
    payload = canonical(value) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        previous = path.lstat()
    except FileNotFoundError:
        previous = None
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            if previous is not None and stat.S_ISREG(previous.st_mode):
                os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode))
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def json_copy(value: Any) -> Any:
    return json.loads(canonical(value))
