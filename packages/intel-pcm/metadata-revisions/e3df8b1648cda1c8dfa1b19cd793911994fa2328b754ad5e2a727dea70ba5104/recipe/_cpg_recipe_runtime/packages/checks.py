"""Run declared installation checks and retain their actual, bounded results.

Checks execute argv arrays. Shells are used only when a package explicitly names
one in argv. Version and availability probes never imply functional qualification.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import string
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence


_KINDS = ("version", "availability", "functional", "hardware")
_STATUSES = ("passed", "failed", "blocked", "not_run")
_VALUES = {"prefix", "source", "build", "assets", "tools", "jobs", "recipe", "package_name", "version", "python"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")


def classify_legacy_check(argv, *, requires_host=False) -> str:
    """Classify an old untyped smoke invocation without upgrading basic probes.

    This is a migration/receipt helper, not a replacement for an authored
    package's declared check kind. Recognized version, discovery, presence and
    syntax invocations retain their limited meaning even for host tools.
    """
    if (isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence) or not argv
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv)):
        raise ValueError("Legacy check argv must be a nonempty string sequence")
    arguments = argv[1:]
    if any(arg in {"--version", "-version", "-V", "version"} for arg in arguments):
        return "version"
    if any(arg in {"--help", "-help", "-h", "help", "--show-config", "--list", "list",
                   "--list-tests", "--list-events", "--benchmark_list_tests", "--benchmark_list_tests=true"}
           for arg in arguments):
        return "availability"
    executable = Path(argv[0]).name
    if (executable in {"test", "["}
            or executable == "perl" and "-c" in arguments
            or executable in {"sh", "bash", "dash", "zsh"} and "-n" in arguments):
        return "availability"
    return "hardware" if requires_host else "functional"


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def expand(value: str, values: Mapping) -> str:
    """Expand documented path placeholders without attribute access or evaluation."""
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("Check arguments must be NUL-free strings")
    output = []
    for literal, field, fmt, conversion in string.Formatter().parse(value):
        output.append(literal)
        if field is None:
            continue
        if conversion:
            raise ValueError("Check placeholders do not support conversions")
        dependency = re.fullmatch(r"dependencies\.(.+)\.(prefix|source)", field)
        if field in {"dependency_prefix", "dependency_source"} and _ID.fullmatch(fmt):
            dependency_id, location = fmt, field.removeprefix("dependency_")
        elif dependency and not fmt and _ID.fullmatch(dependency[1]):
            dependency_id, location = dependency[1], dependency[2]
        else:
            dependency_id = None
        if dependency_id is not None:
            key = f"dependency_{location}:{dependency_id}"
            replacement = values.get(key)
            if replacement is None:
                replacement = values.get("dependencies", {}).get(dependency_id, {}).get(location)
        elif field in _VALUES and not fmt:
            replacement = values.get(field)
        else:
            raise ValueError("Unsupported check placeholder: " + field)
        if replacement is None:
            raise ValueError("Unresolved check placeholder: " + field)
        replacement = str(replacement)
        if "\0" in replacement:
            raise ValueError("Check placeholder values cannot contain NUL")
        output.append(replacement)
    return "".join(output)


def _status(results: list[dict]) -> str:
    if not results:
        return "not_run"
    for status in ("failed", "blocked", "not_run"):
        if any(row["status"] == status for row in results):
            return status
    return "passed"


def summarize(results: Sequence[Mapping]) -> dict:
    """Summarize observed results, keeping absent check kinds unverified."""
    rows = [dict(row) for row in results]
    for row in rows:
        if row.get("kind") not in _KINDS or row.get("status") not in _STATUSES:
            raise ValueError("Invalid check result kind or status")
    return {"status": _status(rows), "results": rows,
            "counts": {status: sum(r["status"] == status for r in rows) for status in _STATUSES},
            **{kind + "_status": _status([r for r in rows if r["kind"] == kind]) for kind in _KINDS},
            "qualification": "Only the declared checks were assessed; this is not full-feature or benchmark qualification."}


def _validate(checks: Sequence[Mapping]) -> list[dict]:
    if isinstance(checks, (str, bytes)) or not isinstance(checks, Sequence):
        raise ValueError("Checks must be a sequence of mappings")
    rows, seen = [], set()
    for raw in checks:
        if not isinstance(raw, Mapping):
            raise ValueError("Each check must be a mapping")
        row = dict(raw)
        identifier = row.get("id")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier in seen:
            raise ValueError("Check IDs must be safe and unique")
        seen.add(identifier)
        if row.get("kind") not in _KINDS:
            raise ValueError("Check kind must be version, availability, functional or hardware")
        argv = row.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or "\0" in a for a in argv):
            raise ValueError("Check argv must be a nonempty NUL-free string list")
        timeout = row.setdefault("timeout_seconds", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Check timeout_seconds must be positive and finite")
        expected = row.setdefault("expected_returncode", 0)
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ValueError("Check expected_returncode must be an integer")
        blocked = row.setdefault("blocked_returncodes", [])
        if (not isinstance(blocked, list) or any(isinstance(c, bool) or not isinstance(c, int) for c in blocked)
                or expected in blocked or (blocked and row["kind"] != "hardware")):
            raise ValueError("Only hardware checks may declare distinct blocked_returncodes")
        for key in ("requires_commands", "requires_paths"):
            items = row.setdefault(key, [])
            if not isinstance(items, list) or any(not isinstance(v, str) or not v or "\0" in v for v in items):
                raise ValueError(key + " must be a list of nonempty NUL-free strings")
        if "stdout_regex" in row:
            if not isinstance(row["stdout_regex"], str):
                raise ValueError("stdout_regex must be a string")
            re.compile(row["stdout_regex"])
        if "cwd" in row and (not isinstance(row["cwd"], str) or not row["cwd"] or "\0" in row["cwd"]):
            raise ValueError("Check cwd must be a nonempty NUL-free string")
        rows.append(row)
    return rows


def _write_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _log(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def _kill(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_checks(checks, *, values, output_dir, environment=None, pass_fds=()) -> dict:
    """Run all declared checks, persisting partial evidence after each result.

    ``environment`` overlays the inherited process environment and is never
    copied into a receipt. ``output_dir`` must not contain a previous checks.json.
    Explicit missing prerequisites block a check. Hardware probes may use an
    explicitly declared return code (usually 77) for unavailable host facilities.
    Internal callers can pass an already-held operation lock to subprocesses;
    a hook then retains that lock if its controller is terminated. Recipes must
    wait for their subprocesses and must not detach background daemons.
    """
    declarations = _validate(checks)
    if (not isinstance(pass_fds, (tuple, list))
            or any(type(fd) is not int or fd < 0 for fd in pass_fds)):
        raise ValueError('pass_fds must contain valid open file descriptors')
    for descriptor in pass_fds:
        os.fstat(descriptor)
    output = Path(output_dir).absolute()
    if output.is_symlink():
        raise ValueError("Check output must be a real directory")
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o755)
    receipt = output / "checks.json"
    if receipt.exists() or receipt.is_symlink():
        raise FileExistsError("Check evidence already exists: " + str(receipt))
    runtime = os.environ.copy()
    if environment is not None:
        if not isinstance(environment, Mapping) or any(
                not isinstance(k, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)
                or not isinstance(v, str) or "\0" in v for k, v in environment.items()):
            raise ValueError("Check environment must contain valid variable names and NUL-free string values")
        runtime.update(environment)
    rows = [{**item, "status": "not_run", "returncode": None, "timed_out": False} for item in declarations]
    started = _utc()

    def publish():
        result = {"schema_version": 1, "started_utc": started, "updated_utc": _utc(), **summarize(rows)}
        _write_json(receipt, result)
        return result

    publish()
    for number, row in enumerate(rows, 1):
        stdout = output / f"{number:04d}-{row['id']}.stdout.log"
        stderr = output / f"{number:04d}-{row['id']}.stderr.log"
        if any(p.exists() or p.is_symlink() for p in (stdout, stderr)):
            raise FileExistsError("Check log already exists: " + row["id"])
        process, began = None, time.monotonic()
        row["started_utc"] = _utc()
        try:
            row["argv"] = [expand(a, values) for a in row["argv"]]
            row["cwd"] = str(Path(expand(row.get("cwd", str(values.get("prefix", Path.cwd()))), values)).absolute())
            missing = []
            for command in row["requires_commands"]:
                command = expand(command, values)
                found = (Path(row["cwd"]) / command).is_file() and os.access(Path(row["cwd"]) / command, os.X_OK) if "/" in command else shutil.which(command, path=runtime.get("PATH"))
                if not found:
                    missing.append("command: " + command)
            for required in row["requires_paths"]:
                path = Path(row["cwd"]) / expand(required, values)
                if not path.exists():
                    missing.append("path: " + str(path))
            if missing:
                row.update(status="blocked", reason="Missing declared prerequisites: " + "; ".join(missing))
                continue
            with stdout.open("xb") as out, stderr.open("xb") as err:
                process = subprocess.Popen(row["argv"], cwd=row["cwd"], env=runtime,
                                           stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                           start_new_session=True, pass_fds=tuple(pass_fds))
                try:
                    row["returncode"] = process.wait(timeout=row["timeout_seconds"])
                except subprocess.TimeoutExpired:
                    _kill(process)
                    row.update(returncode=process.returncode, timed_out=True)
            if row["timed_out"]:
                row.update(status="failed", reason="Check exceeded its declared timeout")
            elif row["returncode"] in row["blocked_returncodes"]:
                row.update(status="blocked", reason="Hardware probe reported unavailable host facilities using a declared blocked return code")
            elif row["returncode"] != row["expected_returncode"]:
                row.update(status="failed", reason="Check returned an unexpected exit code")
            elif "stdout_regex" in row and not re.search(row["stdout_regex"], stdout.read_text(errors="replace")):
                row.update(status="failed", reason="Check output did not match stdout_regex")
            else:
                row["status"] = "passed"
        except (OSError, ValueError) as error:
            row.update(status="failed", reason=f"{type(error).__name__}: {error}")
        except BaseException:
            if process is not None:
                _kill(process)
                row["returncode"] = process.returncode
            row.update(status="failed", reason="Check interrupted before completion", interrupted=True)
            raise
        finally:
            row["duration_seconds"] = time.monotonic() - began
            row["finished_utc"] = _utc()
            for name, path in (("stdout", stdout), ("stderr", stderr)):
                if path.is_file():
                    path.chmod(0o644)
                    row[name] = _log(path)
            publish()
    return publish()
