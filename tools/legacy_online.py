#!/usr/bin/env python3
"""Retain, reproduce and test legacy original-material acquisition recipes.

These recipes acquire locked original bytes. They are not CPG installation
methods and successful acquisition never qualifies a source build or runtime.
All functions are independent of import_archives/release and use only stdlib.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit


FORMAT = "compiler-playground-original-material-online-recipe-v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9.+_-]*\Z")
MAX_RECIPE_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 256


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _require(value, message):
    if not value:
        raise ValueError(message)


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _relative(value):
    _require(isinstance(value, str) and value and value != ".", "Expected a relative file path")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and ".." not in path.parts and "\\" not in value
             and path.as_posix() == value and not any(ord(c) < 32 for c in value),
             "Unsafe recipe path: " + repr(value))
    return path


def _mode(value):
    _require(type(value) is int and 0 <= value <= 0o777, "Invalid ordinary-file mode")
    return value


def validate_descriptor(value):
    _require(isinstance(value, dict) and value.get("format") == FORMAT, "Unsupported legacy online format")
    _require(isinstance(value.get("resource_id"), str) and IDENTIFIER.fullmatch(value["resource_id"]),
             "Invalid recipe resource ID")
    _require(isinstance(value.get("original_version"), str) and value["original_version"].strip(),
             "Missing original version")
    target = value.get("original_target")
    _require(isinstance(target, dict) and all(isinstance(target.get(k), str) and target[k].strip()
             for k in ("os", "arch", "distribution", "distribution_version")), "Incomplete original target")
    sources = value.get("original_sources")
    _require(isinstance(sources, list) and sources, "Missing exact original sources")
    source_ids = set()
    for lock in sources:
        _require(isinstance(lock, dict) and isinstance(lock.get("id"), str)
                 and IDENTIFIER.fullmatch(lock["id"]) and lock["id"] not in source_ids,
                 "Invalid or duplicate source ID")
        source_ids.add(lock["id"])
        _require(isinstance(lock.get("sha256"), str) and SHA256.fullmatch(lock["sha256"])
                 and type(lock.get("bytes")) is int and lock["bytes"] > 0, "Incomplete source byte lock")
        url = lock.get("url")
        _require(isinstance(url, str) and not any(ord(c) <= 32 for c in url), "Invalid original source URL")
        parsed = urlsplit(url)
        _require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.fragment, "Original sources require credential-free HTTPS")
        if lock.get("material_path") is not None:
            _relative(lock["material_path"])
    rows = value.get("files")
    _require(isinstance(rows, list) and 1 <= len(rows) < MAX_MEMBERS, "Invalid recipe file inventory")
    files = {}
    for row in rows:
        _require(isinstance(row, dict), "File inventory entries must be objects")
        path = _relative(row.get("path")).as_posix()
        _require(path != "manifest.json" and path not in files, "Duplicate or reserved inventory path")
        _require(type(row.get("bytes")) is int and 0 <= row["bytes"] <= MAX_RECIPE_BYTES
                 and isinstance(row.get("sha256"), str) and SHA256.fullmatch(row["sha256"]),
                 "Invalid recipe file byte identity")
        _mode(row.get("mode"))
        files[path] = row
    _require("acquire.py" in files, "Legacy acquisition entry point is missing")
    for path in files:
        _require(not any(p.as_posix() in set(files) | {"manifest.json"} for p in PurePosixPath(path).parents),
                 "Recipe files overlap as parent and child")
    return value


def _file_identity(path):
    return {"sha256": sha256(path), "bytes": Path(path).stat().st_size}


def inspect_recipe(archive):
    """Verify every member before returning metadata; never execute or extract."""
    archive = Path(archive)
    _require(archive.is_file() and not archive.is_symlink(), "Recipe archive must be an ordinary file")
    _require(archive.stat().st_size <= MAX_RECIPE_BYTES, "Online recipe archive exceeds the small-recipe limit")
    original = _file_identity(archive)
    contents, members, total = {}, [], 0
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle:
            name = _relative(member.name).as_posix()
            _require(member.isreg() and not member.issparse(), "Online recipes contain only ordinary files")
            _require(name not in contents and len(contents) < MAX_MEMBERS, "Duplicate or excessive archive members")
            _mode(member.mode)
            total += member.size
            _require(0 <= member.size <= MAX_RECIPE_BYTES and total <= MAX_RECIPE_BYTES,
                     "Online recipe expanded size exceeds the small-recipe limit")
            with handle.extractfile(member) as stream:
                raw = stream.read(member.size + 1)
            _require(len(raw) == member.size, "Truncated recipe member")
            contents[name] = raw
            members.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": member.size,
                            "mode": member.mode, "type": member.type.decode("ascii"), "uid": member.uid,
                            "gid": member.gid, "uname": member.uname, "gname": member.gname,
                            "mtime": member.mtime, "pax_headers": dict(member.pax_headers)})
    _require("manifest.json" in contents, "Legacy online manifest is missing")
    descriptor = validate_descriptor(_json(contents["manifest.json"]))
    expected = {row["path"]: row for row in descriptor["files"]}
    _require(set(contents) == set(expected) | {"manifest.json"}, "Missing or undeclared recipe files")
    for row in members:
        if row["path"] in expected:
            _require(all(row[key] == expected[row["path"]][key] for key in ("sha256", "bytes", "mode")),
                     "Recipe member hash, size or mode differs: " + row["path"])
    _require(_file_identity(archive) == original, "Recipe archive changed during verification")
    return {**original, "descriptor": descriptor, "archive_members": members}


def _slug(value, limit):
    original = str(value)
    cleaned = re.sub(r"[^a-zA-Z0-9.+_-]+", "-", original).strip("-.") or "unknown"
    if cleaned != original or len(cleaned) > limit:
        cleaned = cleaned[:limit - 13] + "-" + hashlib.sha256(original.encode()).hexdigest()[:12]
    return cleaned


def artifact_identity(descriptor, checksum):
    _require(isinstance(checksum, str) and SHA256.fullmatch(checksum), "Invalid archive hash")
    return {"id": descriptor["resource_id"], "version": descriptor["original_version"],
            "build": "recipe-v1-" + checksum[:12], "target": copy.deepcopy(descriptor["original_target"]),
            "method": "online-recipe", "sha256": checksum}


def artifact_name(descriptor, checksum):
    row = artifact_identity(descriptor, checksum)
    target = row["target"]
    values = [_slug(row["id"], 60), _slug(row["version"], 40), _slug(row["build"], 36),
              "online", _slug(target["os"] + "-" + target["arch"], 26), checksum[:20]]
    return "cpg--" + "--".join(values) + ".cpgrecipe.tar.gz"


def _ordinary_directory(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        _require(not part.is_symlink(), "Recipe destination traverses a symlink")
    return path


def verify_template(template, record):
    template = _ordinary_directory(template)
    _require(template.is_dir(), "Missing unpacked recipe template")
    members = record["archive_members"]
    expected = {row["path"]: row for row in members}
    _require(len(expected) == len(members), "Duplicate retained archive member")
    actual = set()
    parents = {parent.as_posix() for name in expected for parent in PurePosixPath(name).parents
               if parent != PurePosixPath(".")}
    for path in template.rglob("*"):
        _require(not path.is_symlink(), "Unpacked recipe contains a symlink")
        if path.is_dir():
            _require(path.relative_to(template).as_posix() in parents, "Unpacked recipe contains an undeclared directory")
            continue
        _require(path.is_file(), "Unpacked recipe contains a non-file")
        name = path.relative_to(template).as_posix()
        _require(name in expected, "Unpacked recipe contains an undeclared file")
        row = expected[name]
        _relative(name)
        _require(_file_identity(path) == {k: row[k] for k in ("sha256", "bytes")}
                 and path.stat().st_mode & 0o7777 == _mode(row["mode"]), "Unpacked recipe member changed: " + name)
        actual.add(name)
    _require(actual == set(expected), "Unpacked recipe members are missing")
    descriptor = validate_descriptor(_json((template / "manifest.json").read_bytes()))
    _require(set(actual) == {row["path"] for row in descriptor["files"]} | {"manifest.json"},
             "Unpacked recipe inventory differs")
    for row in descriptor["files"]:
        _require(all(expected[row["path"]][key] == row[key] for key in ("sha256", "bytes", "mode")),
                 "Retained archive headers differ from the recipe inventory")
    return descriptor


def import_recipe(archive, root, origin=None):
    """Return an artifact record and atomically retain its exact authored files.

    The caller owns catalog writes, merging origins and qualification updates.
    """
    checked = inspect_recipe(archive)
    descriptor, checksum = checked["descriptor"], checked["sha256"]
    root = _ordinary_directory(root)
    destination = _ordinary_directory(root / "packages" / descriptor["resource_id"] / "online" / checksum)
    record = {**artifact_identity(descriptor, checksum), "bytes": checked["bytes"], "online_format": FORMAT,
              "asset_name": artifact_name(descriptor, checksum), "template": destination.relative_to(root).as_posix(),
              "archive_members": checked["archive_members"], "structure": "passed", "build_check": "not_run",
              "functional": "not_run", "release_eligible": False,
              "qualification_scope": "exact_original_source_acquisition_only",
              "source_build_or_runtime_qualified": False, "origins": [origin] if origin else []}
    if destination.exists():
        verify_template(destination, record)
        return record
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".recipe-import-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "template"
        stage.mkdir()
        with tarfile.open(archive, "r:gz") as handle:
            for row in record["archive_members"]:
                path = stage / _relative(row["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                with handle.extractfile(row["path"]) as source, path.open("xb") as output:
                    shutil.copyfileobj(source, output)
                path.chmod(row["mode"])
        verify_template(stage, record)
        _require(_file_identity(archive) == {k: checked[k] for k in ("sha256", "bytes")},
                 "Recipe archive changed during import")
        os.rename(stage, destination)
    return record


def repack(template, record, output, *, require_original=True):
    """Reproduce retained tar member order/headers with deterministic gzip.

    An unsupported original compression/header encoding fails closed by default.
    With require_original=False, returned bytes receive their own new identity.
    """
    descriptor = verify_template(template, record)
    template, output = Path(template).absolute(), _ordinary_directory(output)
    _require(not output.is_relative_to(template), "Repack output must be outside the immutable template")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".recipe-repack-", dir=output) as temporary:
        candidate = Path(temporary) / "recipe.tar.gz"
        with candidate.open("wb") as stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for row in record["archive_members"]:
                    info = tarfile.TarInfo(row["path"])
                    info.size, info.mode, info.type = row["bytes"], row["mode"], row["type"].encode("ascii")
                    for name in ("uid", "gid", "uname", "gname", "mtime", "pax_headers"):
                        setattr(info, name, copy.deepcopy(row[name]))
                    with (template / _relative(row["path"])).open("rb") as source:
                        archive.addfile(info, source)
        verified = inspect_recipe(candidate)
        _require(verified["descriptor"] == descriptor, "Repacked descriptor changed")
        identical = all(verified[key] == record[key] for key in ("sha256", "bytes"))
        _require(identical or not require_original, "Repacked recipe differs from the original byte identity")
        target = output / artifact_name(descriptor, verified["sha256"])
        if target.exists() or target.is_symlink():
            _require(not target.is_symlink() and target.is_file()
                     and _file_identity(target) == {k: verified[k] for k in ("sha256", "bytes")},
                     "Refusing to overwrite different recipe bytes")
        else:
            os.link(candidate, target)
    return {**artifact_identity(descriptor, verified["sha256"]), "bytes": verified["bytes"], "path": str(target),
            "asset_name": target.name, "byte_identical_to_original": identical, "original_sha256": record["sha256"]}


def _log(path, content):
    path.write_bytes(content)
    return {"path": str(path), **_file_identity(path)}


def qualify_upstream(template, record, output, *, timeout=180):
    """Run the authentic entry point WITHOUT a verification mirror.

    A locked output and an observed successful command are both required.
    Transport failures are blocked; wrong bytes and script failures are failed.
    """
    descriptor = verify_template(template, record)
    _require(len(descriptor["original_sources"]) == 1, "This legacy acquisition runner supports one exact source")
    _require(isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0,
             "Acquisition timeout must be positive")
    output = _ordinary_directory(output)
    _require(not output.is_relative_to(Path(template).absolute()), "Acquisition output must be outside the recipe")
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "original-source.archive"
    argv = [sys.executable, "-B", str(Path(template).absolute() / "acquire.py"), "--output", str(destination)]
    result = {"scope": "exact_original_source_acquisition_only", "upstream_url": descriptor["original_sources"][0]["url"],
              "verification_mirror_used": False, "source_build_or_runtime_qualified": False,
              "argv": argv, "status": "running"}
    try:
        process = subprocess.run(argv, cwd=output, capture_output=True, timeout=timeout,
                                 env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        result.update(returncode=process.returncode, timed_out=False,
                      stdout=_log(output / "stdout.log", process.stdout), stderr=_log(output / "stderr.log", process.stderr))
        if process.returncode:
            text = process.stderr.decode(errors="replace")
            transport = re.search(r"HTTP Error [45][0-9]{2}|urlopen error|timed out|Temporary failure in name resolution|"
                                  r"Name or service not known|Connection refused|Network is unreachable", text, re.I)
            result.update(status="blocked" if transport else "failed", reason=text[-4000:])
        else:
            lock = descriptor["original_sources"][0]
            _require(destination.is_file() and not destination.is_symlink(), "Acquirer did not produce an ordinary source archive")
            observed = _file_identity(destination)
            _require(observed == {k: lock[k] for k in ("sha256", "bytes")}, "Acquired output differs from the exact original source")
            result.update(status="passed", upstream_https_transfer_tested=True,
                          source={"path": str(destination), **observed})
    except subprocess.TimeoutExpired as error:
        result.update(status="blocked", reason="Original upstream acquisition timed out", timed_out=True,
                      stdout=_log(output / "stdout.log", error.stdout or b""),
                      stderr=_log(output / "stderr.log", error.stderr or b""))
    except (OSError, ValueError) as error:
        result.update(status="failed", reason=str(error))
    if result["status"] != "passed":
        result["upstream_https_transfer_tested"] = False
    (output / "qualification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def rejection_controls(template, record, output, *, raw=None, max_bytes=64 * 1024 * 1024, timeout=60):
    """Exercise the unchanged acquirer against bounded loopback fixtures.

    The positive control requires the genuine locked raw input. Without it,
    same-size incorrect bytes test the hash guard; no positive transfer or
    upstream HTTPS qualification is claimed. Fixtures stream without large files.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    descriptor = verify_template(template, record)
    _require(len(descriptor["original_sources"]) == 1, "Controls require one exact source")
    lock = descriptor["original_sources"][0]
    _require(lock["bytes"] <= max_bytes, "Source exceeds the explicit local-control byte budget")
    if raw is not None:
        raw = Path(raw)
        _require(raw.is_file() and not raw.is_symlink()
                 and _file_identity(raw) == {k: lock[k] for k in ("sha256", "bytes")}, "Control input differs from the original lock")
    output = _ordinary_directory(output)
    _require(not output.is_relative_to(Path(template).absolute()), "Control output must be outside the recipe")
    output.mkdir(parents=True, exist_ok=False)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            case = self.path.strip("/")
            requests.append(case)
            size = lock["bytes"] + (1 if case == "oversized" else -1 if case == "truncated" else 0)
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            source = raw.open("rb") if raw is not None else None
            try:
                offset = 0
                while offset < size:
                    count = min(1024 * 1024, size - offset)
                    block = source.read(count) if source is not None else b"\0" * count
                    block += b"\0" * (count - len(block))
                    if offset == 0 and case == "same-size-bad-sha":
                        block = bytes([block[0] ^ 1]) + block[1:]
                    self.wfile.write(block)
                    offset += len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                if source is not None:
                    source.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    result = {"scope": "loopback_acquirer_controls_only", "verification_mirror_used": True,
              "upstream_https_transfer_tested": False, "source_build_or_runtime_qualified": False,
              "positive_control": "not_run_exact_raw_absent", "cases": [], "status": "running"}

    def call(case, destination):
        argv = [sys.executable, "-B", str(Path(template).absolute() / "acquire.py"),
                "--output", str(destination), "--verification-mirror", base + "/" + case]
        completed = subprocess.run(argv, cwd=output, capture_output=True, timeout=timeout,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return {"case": case, "argv": argv, "returncode": completed.returncode,
                "stdout": _log(output / (case + ".stdout.log"), completed.stdout),
                "stderr": _log(output / (case + ".stderr.log"), completed.stderr)}, completed

    try:
        if raw is not None:
            destination = output / "positive.archive"
            row, completed = call("positive", destination)
            result["cases"].append(row)
            _require(completed.returncode == 0 and _file_identity(destination) == {k: lock[k] for k in ("sha256", "bytes")},
                     "Exact-input local transfer did not succeed")
            destination.unlink()
            row["status"] = "passed"
            result["positive_control"] = "passed_local_mirror_only"
        for case in ("truncated", "same-size-bad-sha", "oversized"):
            destination = output / (case + ".archive")
            row, completed = call(case, destination)
            result["cases"].append(row)
            text = completed.stderr.decode(errors="replace")
            expected = "oversize transfer" if case == "oversized" else "SHA/size mismatch"
            _require(completed.returncode != 0 and expected in text and not destination.exists(),
                     "Invalid transfer was accepted or rejected for an unrelated reason: " + case)
            row.update(status="passed", expected_rejection=True, destination_absent=True,
                       fixture="one_byte_corruption_of_exact_input" if raw is not None and case == "same-size-bad-sha"
                       else "bounded_synthetic_or_truncated_input")
        destination = output / "overwrite.archive"
        marker = b"existing output must survive\n"
        destination.write_bytes(marker)
        count = len(requests)
        row, completed = call("overwrite", destination)
        result["cases"].append(row)
        _require(completed.returncode != 0 and "output already exists" in completed.stderr.decode(errors="replace")
                 and destination.read_bytes() == marker and len(requests) == count,
                 "Existing output was modified or overwrite triggered a transfer")
        destination.unlink()
        row.update(status="passed", expected_rejection=True, existing_output_unchanged=True, network_request_made=False)
        logs = {case["case"] + suffix for case in result["cases"] for suffix in (".stdout.log", ".stderr.log")}
        _require({path.name for path in output.iterdir()} == logs, "Acquisition controls leaked an unexpected file")
        result["status"] = "passed"
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        result.update(status="failed", reason=str(error))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    result["observed_loopback_requests"] = requests
    (output / "controls.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def qualification_errors(record, descriptor):
    """Gate recipe publication on exact reproduction and actual acquisition.

    This gate qualifies the recipe's acquisition behavior, never the original
    software's build, runtime, benchmark or hardware behavior.
    """
    errors = []
    identity = artifact_identity(descriptor, record["sha256"])
    if any(record.get(key) != value for key, value in identity.items()):
        errors.append("Recipe identity differs from its descriptor")
    qualification = record.get("qualification", {})
    reproduction = qualification.get("reproduction", {})
    if (record.get("structure") != "passed" or record.get("build_check") != "passed"
            or reproduction.get("sha256") != record["sha256"]
            or reproduction.get("bytes") != record["bytes"]
            or reproduction.get("byte_identical_to_original") is not True):
        errors.append("Recipe must reproduce its exact original archive bytes")
    upstream = qualification.get("upstream", {})
    sources = descriptor["original_sources"]
    lock = sources[0]
    if (len(sources) != 1 or upstream.get("status") != "passed"
            or upstream.get("returncode") != 0 or upstream.get("timed_out") is not False
            or upstream.get("upstream_https_transfer_tested") is not True
            or upstream.get("verification_mirror_used") is not False
            or "--verification-mirror" in upstream.get("argv", [])
            or upstream.get("upstream_url") != lock["url"]
            or any(upstream.get("source", {}).get(key) != lock[key] for key in ("sha256", "bytes"))):
        errors.append("Actual original HTTPS acquisition must succeed against the exact source lock")
    controls = qualification.get("controls", {})
    cases = controls.get("cases", [])
    expected = {"positive", "truncated", "same-size-bad-sha", "oversized", "overwrite"}
    observed = {row.get("case"): row for row in cases}
    if (controls.get("status") != "passed" or controls.get("verification_mirror_used") is not True
            or controls.get("upstream_https_transfer_tested") is not False
            or controls.get("positive_control") != "passed_local_mirror_only"
            or len(cases) != len(expected) or set(observed) != expected
            or any(row.get("status") != "passed" or row.get("returncode") != (0 if name == "positive" else 1)
                   for name, row in observed.items())
            or any(observed.get(name, {}).get("destination_absent") is not True
                   for name in ("truncated", "same-size-bad-sha", "oversized"))
            or observed.get("overwrite", {}).get("existing_output_unchanged") is not True
            or observed.get("overwrite", {}).get("network_request_made") is not False):
        errors.append("Exact positive transfer and all four rejection controls must pass")
    definition = qualification.get("definition", {})
    if (definition.get("catalog_sha256") != descriptor.get("original_catalog_sha256")
            or definition.get("sources") != sources or definition.get("license_class") != "open"
            or not definition.get("license_id") or definition.get("redistributable") is not True):
        errors.append("The exact original catalog must establish public redistribution")
    if (record.get("source_build_or_runtime_qualified") is not False
            or upstream.get("source_build_or_runtime_qualified") is not False
            or controls.get("source_build_or_runtime_qualified") is not False):
        errors.append("Acquisition evidence cannot claim source build or runtime qualification")
    for result in (upstream, *cases):
        for name in ("stdout", "stderr"):
            log = result.get(name, {})
            if (not isinstance(log.get("sha256"), str) or not SHA256.fullmatch(log["sha256"])
                    or type(log.get("bytes")) is not int or log["bytes"] < 0
                    or log.get("retained_path") != "catalog/imports/" + record["sha256"] + ".evidence/" + log["sha256"] + ".log"):
                errors.append("Recipe qualification lacks retained " + name + " evidence")
    if record.get("functional") != "passed":
        errors.append("Recipe acquisition functionality has not passed")
    return errors


def record_qualification(root, record, *, definition, reproduction, upstream, controls):
    """Retain observed logs outside the exact template and return a gated record."""
    root = Path(root).absolute()
    descriptor = verify_template(root / record["template"], record)
    definition = Path(definition).absolute()
    _require(definition.is_relative_to(root) and definition.is_file() and not definition.is_symlink(),
             "Original package definition must be a retained repository file")
    spec = _json(definition.read_bytes())
    catalog = spec.get("metadata", {}).get("catalog", {})
    catalog_sha = hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    _require(catalog_sha == descriptor.get("original_catalog_sha256")
             and spec.get("metadata", {}).get("catalog_sha256") == catalog_sha
             and spec.get("sources") == descriptor["original_sources"]
             and spec.get("id") == descriptor["resource_id"]
             and spec.get("version") == descriptor["original_version"]
             and spec.get("target") == descriptor["original_target"],
             "Original source definition/catalog differs from the online recipe")
    result = copy.deepcopy(record)
    qualification = {"scope": "exact_original_source_acquisition_only",
                     "upstream": copy.deepcopy(upstream), "controls": copy.deepcopy(controls),
                     "reproduction": copy.deepcopy(reproduction),
                     "definition": {"path": definition.relative_to(root).as_posix(), "sha256": sha256(definition),
                                    "catalog_sha256": catalog_sha, "sources": copy.deepcopy(spec["sources"]),
                                    **{key: catalog.get(key) for key in ("license_class", "license_id", "redistributable")}}}
    for receipt in (qualification["upstream"], *qualification["controls"].get("cases", [])):
        for stream in ("stdout", "stderr"):
            log = receipt.get(stream)
            if not isinstance(log, dict):
                continue
            source = Path(log["path"])
            _require(source.is_file() and not source.is_symlink()
                     and _file_identity(source) == {key: log[key] for key in ("sha256", "bytes")},
                     "Observed acquisition log has changed")
            relative = "catalog/imports/" + record["sha256"] + ".evidence/" + log["sha256"] + ".log"
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                _require(not destination.is_symlink() and _file_identity(destination) == _file_identity(source),
                         "Retained acquisition log has changed")
            else:
                shutil.copyfile(source, destination)
                destination.chmod(0o644)
            log["retained_path"] = relative
    result["qualification"] = qualification
    result["build_check"] = "passed" if (reproduction.get("byte_identical_to_original") is True
                                       and reproduction.get("sha256") == record["sha256"]
                                       and reproduction.get("bytes") == record["bytes"]) else "failed"
    result["functional"] = "passed" if upstream.get("status") == controls.get("status") == "passed" else "blocked_or_failed"
    result["qualification_errors"] = qualification_errors(result, descriptor)
    result["release_eligible"] = not result["qualification_errors"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("archive", type=Path)
    imported = sub.add_parser("import")
    imported.add_argument("archive", type=Path)
    imported.add_argument("--root", type=Path, required=True)
    for name in ("repack", "qualify", "controls"):
        command = sub.add_parser(name)
        command.add_argument("template", type=Path)
        command.add_argument("--record", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "repack":
            command.add_argument("--allow-new-identity", action="store_true")
        elif name == "qualify":
            command.add_argument("--timeout", type=float, default=180)
        else:
            command.add_argument("--raw", type=Path)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        result = inspect_recipe(args.archive)
    elif args.command == "import":
        result = import_recipe(args.archive, args.root, {"archive": args.archive.name})
    else:
        record = _json(args.record.read_bytes())
        if args.command == "repack":
            result = repack(args.template, record, args.output, require_original=not args.allow_new_identity)
        elif args.command == "qualify":
            result = qualify_upstream(args.template, record, args.output, timeout=args.timeout)
        else:
            result = rejection_controls(args.template, record, args.output, raw=args.raw)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("status") in {"failed", "blocked"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
