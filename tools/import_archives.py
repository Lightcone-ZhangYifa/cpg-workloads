#!/usr/bin/env python3
"""Inspect legacy delivery archives one member at a time and retain recipe sources.

This is a migration tool, not an installer. Package integrity and extraction are
delegated to Compiler Playground. Immutable payloads never enter this checkout.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


FORMAT = "compiler_playground_resource_package"
WORKER = re.compile(r"(?:workers?|wokers?)[-_ ]*\d", re.I)
DECLARED_CPG = re.compile(r"\.cpg(?:pkg|recipe)(?:\.|$)", re.I)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def safe_relative(name):
    if not isinstance(name, str) or not name or name == ".":
        raise ValueError("Archive paths must be nonempty relative names")
    path = PurePosixPath(name)
    if (path.is_absolute() or ".." in path.parts or "\\" in name or
            path.as_posix() != name or any(ord(c) < 32 for c in name)):
        raise ValueError("Unsafe archive member: " + repr(name))
    return path


def source_locks_complete(manifest):
    """Allow only explicit lock extensions that preserve every fixed source field."""
    spec = manifest["package"]
    resolved = {row["id"]: row for row in manifest.get("resolved_sources", [])}
    acquisition = spec["recipe"].get("acquisition_lock")
    if isinstance(acquisition, dict) and "id" in acquisition:
        resolved.setdefault(acquisition["id"], acquisition)
    locks = []
    for original in spec["sources"]:
        lock = resolved.get(original["id"], original)
        if any(value != lock.get(key) for key, value in original.items()
               if not (key in {"sha256", "bytes"} and value is None)):
            return False
        locks.append(lock)
    locks.extend(spec["recipe"].get("additional_acquisition_locks", []))
    return all(isinstance(row.get("sha256"), str)
               and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
               and type(row.get("bytes")) is int and row["bytes"] >= 0 for row in locks)


def qualification_errors(record, manifest, template=None):
    """One publication gate, shared by import, planning, build, and repository CI."""
    from static_review import POLICY, common_qualification_errors, static_review
    spec, method = manifest["package"], manifest["method"]
    errors = common_qualification_errors(record, manifest)
    if record.get("review_policy") == POLICY:
        if template is None:
            if record.get("static_review", {}).get("status") != "passed":
                errors.append("Static review has not passed")
            return errors
        return static_review(record, manifest, template)["errors"]
    if record.get("build_check") != "passed":
        errors.append("Structure and build/install qualification must pass")
    if not source_locks_complete(manifest):
        errors.append("Effective source locks are incomplete or changed fixed fields")
    apt = method == "wrapper" and spec["provider"] == "apt" and spec["recipe"].get("manager") == "apt"
    if record.get("functional") == "exempt_apt_wrapper":
        if not apt or record.get("reproduced_sha256") != record.get("sha256"):
            errors.append("Only exactly rebuilt APT wrappers are exempt from functional checks")
    else:
        errors.extend(installation_errors(record, spec))
    return errors


def installation_errors(record, spec):
    """Require the actual manager receipt to cover this package's declared checks."""
    errors = []
    qualification = record.get("qualification", {})
    if not isinstance(qualification, dict):
        errors.append("Installation qualification must be a receipt object")
        return errors
    installation, checks = qualification.get("installation", {}), qualification.get("checks", {})
    if (qualification.get("status") != "installed" or not isinstance(installation, dict)
            or installation.get("status") != "installed" or not isinstance(checks, dict)
            or checks.get("functional_status") != "passed" or record.get("functional") != "passed"):
        errors.append("An installed non-APT artifact needs observed passing functional checks")
    artifact = qualification.get("package_artifact", {})
    if (not isinstance(artifact, dict) or artifact.get("sha256") != record.get("sha256")
            or type(artifact.get("bytes")) is not int or artifact["bytes"] != record.get("bytes")):
        errors.append("Installation evidence belongs to a different or unidentified archive")
    declarations = {row["id"]: row for row in spec["checks"]}
    results = checks.get("results", []) if isinstance(checks, dict) else []
    if (not isinstance(results, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
                                            for row in results)):
        errors.append("Check evidence must be a list of identified results")
        return errors
    observed = {row["id"]: row for row in results}
    if len(observed) != len(results) or set(observed) != set(declarations):
        errors.append("Check evidence must cover each declared check exactly once")
    if not any(row["kind"] == "functional" for row in declarations.values()):
        errors.append("A non-APT artifact must declare a functional check")
    for identifier, result in observed.items():
        declaration = declarations.get(identifier)
        if declaration is None or result.get("kind") != declaration["kind"]:
            errors.append("Check evidence differs from its declaration: " + identifier)
            continue
        # Hardware observations remain separate from software qualification.
        if declaration["kind"] == "hardware":
            continue
        if (result.get("status") != "passed" or type(result.get("returncode")) is not int
                or result["returncode"] != declaration["expected_returncode"]
                or result.get("timed_out") is not False or result.get("interrupted", False)
                or result.get("stdout_regex") != declaration.get("stdout_regex")):
            errors.append("Declared software check did not complete successfully: " + identifier)
        for stream in ("stdout", "stderr"):
            log = result.get(stream)
            if (not isinstance(log, dict) or not isinstance(log.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", log["sha256"]) is None
                    or type(log.get("bytes")) is not int or log["bytes"] < 0
                    or log.get("retained_path") != "evidence/" + log["sha256"] + ".log"):
                errors.append("Executed check lacks retained " + stream + " evidence: " + identifier)
    return errors


def qualification_logs(qualification):
    """Yield the manager's build/check log identities, not its package payload."""
    for stage, field in (("installation", "evidence"), ("checks", "results")):
        value = qualification.get(stage, {})
        if not isinstance(value, dict):
            continue
        for result in value.get(field, []):
            for name in ("stdout", "stderr"):
                if isinstance(result.get(name), dict):
                    yield result[name]


def retain_qualification(receipt, directory):
    """Keep the same receipt shape on success/failure and retain transient logs."""
    qualification = {key: copy.deepcopy(receipt[key]) for key in (
        "status", "installation", "checks", "package_artifact", "actual_target", "started_utc"
    ) if key in receipt}
    qualification["scope"] = ("Fresh local installation and declared checks; no official benchmark or "
                              "unobserved hardware claim. Log retained_path is relative to the artifact template.")
    for log in qualification_logs(qualification):
        source = Path(log["path"])
        if (source.is_symlink() or not source.is_file() or source.stat().st_size != log["bytes"]
                or sha256(source) != log["sha256"]):
            raise ValueError("Build/check log differs from the manager receipt")
        relative = "evidence/" + log["sha256"] + ".log"
        destination = directory / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if (destination.is_symlink() or destination.stat().st_size != log["bytes"]
                    or sha256(destination) != log["sha256"]):
                raise ValueError("Retained build/check evidence has changed")
        else:
            shutil.copyfile(source, destination)
            destination.chmod(0o644)
        log["retained_path"] = relative
    return qualification


def record_installation(record, receipt, directory):
    qualification = retain_qualification(receipt, directory)
    record["qualification"] = qualification
    record["build_check"] = ("passed" if qualification.get("installation", {}).get("status") == "installed"
                             else "blocked_or_failed")
    record["functional"] = qualification.get("checks", {}).get("functional_status", "not_run")


def sniff(stream):
    """Read bounded tar metadata without expanding an unrelated source archive."""
    try:
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            total = 0
            for number, member in enumerate(archive):
                if number >= 12 or total > 512 * 1024:
                    return None
                total += member.size
                if member.name == "manifest.json" and member.isfile() and member.size <= 64 * 1024 * 1024:
                    value = json.load(archive.extractfile(member))
                    return "package" if isinstance(value, dict) and value.get("kind") == FORMAT else None
                if member.name == "online.json" and member.isfile() and member.size < 8 * 1024 * 1024:
                    value = json.load(archive.extractfile(member))
                    return "online" if isinstance(value, dict) and value.get("kind") == "cpg_online_material_recipe" else None
                if member.name.split("/")[0] not in {
                    "README.md", "offline-manifest.json", "online.json", "recipe", "run.py", "tools"
                }:
                    return None
    except (tarfile.TarError, OSError, ValueError, EOFError):
        return None
    return None


def template_directory(root, spec, checksum):
    identifier = spec["id"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.+_-]*", identifier):
        raise ValueError("Invalid package ID")
    return root / "packages" / identifier / "artifacts" / checksum


def copy_template(archive, destination, manifest):
    """Retain authored recipes and exact manifests, excluding installed payloads."""
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "manifest.json", manifest)
    write_json(destination / "package.json", manifest["package"])
    with tarfile.open(archive, "r:gz") as handle:
        for row in manifest["files"]:
            relative = safe_relative(row["path"])
            if relative.parts[0] not in {"recipe", "tools"}:
                continue
            target = destination.joinpath(*relative.parts)
            if row["kind"] == "directory":
                target.mkdir(parents=True, exist_ok=True)
            elif row["kind"] == "file":
                target.parent.mkdir(parents=True, exist_ok=True)
                with handle.extractfile(row["path"]) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if row["mode"] & 0o111 else 0o644)
                if sha256(target) != row["sha256"]:
                    raise ValueError("Recipe copy hash mismatch")
            elif row["kind"] == "symlink":
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.is_symlink():
                    target.symlink_to(row["target"])
            else:
                raise ValueError("Unexpected template node")


def artifact_name(spec, method, checksum):
    """Use readable components plus the full content identity to avoid collisions."""
    def slug(value, limit):
        original = str(value)
        cleaned = re.sub(r"[^a-zA-Z0-9.+_-]+", "-", original).strip("-.") or "unknown"
        if cleaned != original or len(cleaned) > limit:
            cleaned = cleaned[:limit - 13] + "-" + hashlib.sha256(original.encode()).hexdigest()[:12]
        return cleaned
    target = spec["target"]
    values = [slug(spec["id"], 60), slug(spec["version"], 40), slug(spec["build"], 36),
              method, slug(target["os"] + "-" + target["arch"], 26), checksum[:20]]
    return "cpg--" + "--".join(values) + ".cpgpkg.tar.gz"


def import_package(path, root, origin, *, attempt_build=False, jobs=2, source_overrides=None, static_trust=False):
    from compiler_playground.packages import pack, verify_package
    from compiler_playground.packages.manager import PackageManager

    path, root = Path(path), Path(root)
    checked = verify_package(path)
    manifest, checksum = checked["manifest"], checked["sha256"]
    spec, method = manifest["package"], manifest["method"]
    directory = template_directory(root, spec, checksum)
    copy_template(path, directory, manifest)
    checks = [check for check in spec["checks"] if check["kind"] == "functional"]
    apt = method == "wrapper" and spec["provider"] == "apt" and spec["recipe"].get("manager") == "apt"
    catalog = spec["metadata"].get("catalog", {})
    missing = [name for name in ("license_class", "license_id") if not catalog.get(name)]
    locked = source_locks_complete(manifest)
    record = {
        "id": spec["id"], "version": spec["version"], "build": spec["build"],
        "target": spec["target"], "provider": spec["provider"], "method": method,
        "sha256": checksum, "bytes": checked["bytes"], "manifest_sha256": manifest["manifest_sha256"],
        "template": directory.relative_to(root).as_posix(),
        "asset_name": artifact_name(spec, method, checksum),
        "structure": "passed", "metadata_missing": missing, "source_locks_complete": locked,
        "functional_checks_declared": len(checks),
        "functional": "exempt_apt_wrapper" if apt else "not_run",
        "build_check": "not_run", "release_eligible": False,
        "origins": [origin],
    }
    previous_path = root / "catalog" / "artifacts" / (checksum + ".json")
    if previous_path.exists():
        previous = json.loads(previous_path.read_text())
        for key in ("id", "version", "build", "target", "method", "sha256", "bytes", "manifest_sha256"):
            if previous.get(key) != record[key]:
                raise ValueError("Existing artifact record differs from verified input: " + key)
        for key in ("build_check", "functional", "qualification", "failure", "blocker", "previous_attempts",
                    "reproduced_sha256", "origins", "review_policy", "static_review"):
            if key in previous:
                record[key] = previous[key]
        if origin not in record["origins"]:
            record["origins"].append(origin)
    if apt and (record["build_check"] != "passed" or record.get("reproduced_sha256") != checksum):
        with tempfile.TemporaryDirectory(prefix="cpg-wrapper-rebuild-", dir=path.parent) as temporary:
            output = Path(temporary) / "rebuilt.cpgpkg.tar.gz"
            result = pack(spec, output, method="wrapper",
                          recipe_dir=directory / "recipe" if (directory / "recipe").exists() else None,
                          tools_dir=directory / "tools" if (directory / "tools").exists() else None,
                          provenance=manifest["provenance"], resolved_dependencies=manifest["resolved_dependencies"],
                          resolved_sources=manifest.get("resolved_sources"))
            if result["sha256"] != checksum:
                raise ValueError("Metadata wrapper does not reproduce its original bytes")
            record["build_check"] = "passed"
            record["reproduced_sha256"] = result["sha256"]
        record["functional"] = "exempt_apt_wrapper"
    elif not apt and not checks:
        record["functional"] = "blocked_missing_functional_test"
    elif not apt and attempt_build and installation_errors(record, spec):
        if any(key in record for key in ("qualification", "failure")) or record["build_check"] != "not_run":
            record.setdefault("previous_attempts", []).append({key: copy.deepcopy(record[key]) for key in (
                "build_check", "functional", "qualification", "failure", "blocker") if key in record})
        for key in ("qualification", "failure", "blocker"):
            record.pop(key, None)
        record.update(build_check="not_run", functional="not_run")
        with tempfile.TemporaryDirectory(prefix="cpg-package-check-", dir=path.parent) as temporary:
            base = Path(temporary)
            manager = PackageManager(state=base / "state", prefix_root=base / "prefixes", cache=base / "cache")
            try:
                prefix, environment = base / "install", None
                if method == "wrapper":
                    if spec["recipe"].get("manager") != "pip":
                        raise ValueError("This wrapper needs a separately prepared isolated manager environment; "
                                         "automatic qualification supports APT metadata and fresh pip virtual environments")
                    setup = subprocess.run([sys.executable, "-m", "venv", str(prefix)],
                                           capture_output=True, text=True, timeout=120)
                    if setup.returncode:
                        raise RuntimeError("Could not prepare an isolated Python environment: " + setup.stderr)
                    environment = {"PATH": str(prefix / "bin") + os.pathsep + os.environ.get("PATH", ""),
                                   "VIRTUAL_ENV": str(prefix), "PYTHONNOUSERSITE": "1",
                                   "PIP_REQUIRE_VIRTUALENV": "true", "PIP_CONFIG_FILE": os.devnull,
                                   "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
                receipt = manager.install(path, prefix=prefix, jobs=jobs, check=True,
                                          source_overrides=source_overrides, environment=environment)
                record_installation(record, receipt, directory)
            except BaseException as error:
                record["build_check"] = "blocked_or_failed"
                record["failure"] = {"type": type(error).__name__, "message": str(error)}
                receipts = manager.receipts(include_removed=True)
                if receipts:
                    record_installation(record, receipts[-1], directory)
                if not isinstance(error, Exception):
                    record["qualification_errors"] = qualification_errors(record, manifest)
                    write_json(previous_path, record)
                    raise
    if static_trust:
        from static_review import POLICY, static_review
        record["review_policy"] = POLICY
        record["static_review"] = static_review(record, manifest, directory)
    record["qualification_errors"] = qualification_errors(record, manifest, directory)
    record["release_eligible"] = not record["qualification_errors"]
    write_json(previous_path, record)
    return {key: record[key] for key in ("sha256", "id", "method", "structure", "build_check", "functional", "release_eligible")}


def import_online(path, root, origin):
    checksum = sha256(path)
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate online recipe member")
        for member in members:
            relative = safe_relative(member.name)
            if not member.isfile() or relative.parts[0] in {"payload", "sources"}:
                raise ValueError("An online recipe must contain only ordinary recipe files")
        descriptor = json.load(archive.extractfile("online.json"))
        if descriptor.get("kind") != "cpg_online_material_recipe" or descriptor.get("embedded_payload_bytes") != 0:
            raise ValueError("Unknown online recipe contract")
        identifier = descriptor["resource_id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9.+_-]*", identifier):
            raise ValueError("Invalid recipe resource ID")
        expected = descriptor["recipe_files"]
        if {row["path"] for row in expected} | {"online.json"} != set(names):
            raise ValueError("Online recipe inventory mismatch")
        directory = root / "packages" / identifier / "online" / checksum
        directory.mkdir(parents=True, exist_ok=True)
        for member in members:
            target = directory / safe_relative(member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
        for row in expected:
            target = directory / safe_relative(row["path"])
            if target.stat().st_size != row["bytes"] or sha256(target) != row["sha256"]:
                raise ValueError("Online recipe file integrity mismatch")
    record = {"sha256": checksum, "bytes": path.stat().st_size, "id": identifier, "method": "online-recipe",
              "structure": "passed", "build_check": "not_run", "functional": "not_run",
              "release_eligible": False, "template": directory.relative_to(root).as_posix(), "origins": [origin]}
    write_json(root / "catalog" / "artifacts" / (checksum + ".json"), record)
    return record


@contextmanager
def open_outer_tar(path):
    """Read an outer container sequentially; zstd output never touches disk."""
    with path.open("rb") as source:
        compressed_zstd = source.read(4) == b"\x28\xb5\x2f\xfd"
    if not compressed_zstd:
        with tarfile.open(path, mode="r|*") as archive:
            yield archive
        return
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(["zstd", "-dc", "--", str(path)], stdout=subprocess.PIPE, stderr=errors)
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                yield archive
            process.stdout.close()
            if process.wait(timeout=30):
                errors.seek(0)
                raise ValueError("Invalid zstd container: " + errors.read(4096).decode(errors="replace"))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()


def inspect_archive(path, root, scratch, *, attempt_build=False, depth=0, origin=None, static_trust=False):
    path, root, scratch = Path(path), Path(root), Path(scratch)
    root.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    checksum = sha256(path)
    origin = origin or {"archive": path.name, "sha256": checksum, "bytes": path.stat().st_size}
    receipt = {"archive": path.name, "sha256": checksum, "bytes": path.stat().st_size,
               "packages": [], "online_recipes": [], "nonpackage_members": 0, "errors": [], "worker_excluded": 0}

    def consume(member_path, kind, source):
        try:
            if kind == "package":
                result = import_package(member_path, root, source, attempt_build=attempt_build, static_trust=static_trust)
                receipt["packages"].append(result)
            elif kind == "online":
                receipt["online_recipes"].append(import_online(member_path, root, source))
        except Exception as error:
            receipt["errors"].append({"member": source.get("member", path.name),
                                      "error": type(error).__name__ + ": " + str(error)})

    def inspect_member(name, size, stream):
        normalized = name[2:] if name.startswith("./") else name
        safe_relative(normalized)
        if WORKER.search(name):
            receipt["worker_excluded"] += 1
            return
        # sniff() consumes the stream. Spool only archive-like members so a
        # non-seekable outer TAR does not require extracting the whole tree.
        prefix = stream.read(512)
        archive_like = (prefix.startswith((b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00", b"\x28\xb5\x2f\xfd"))
                        or prefix[257:262] == b"ustar")
        if not archive_like:
            if DECLARED_CPG.search(name):
                receipt["errors"].append({"member": name,
                    "error": "Unsupported or invalid declared CPG archive format/schema"})
            else:
                receipt["nonpackage_members"] += 1
            return
        if size > shutil.disk_usage(scratch).free - 1024 ** 3:
            receipt["errors"].append({"member": name, "error": "Insufficient rolling disk reserve"})
            return
        with tempfile.TemporaryDirectory(prefix="member-", dir=scratch) as temporary:
            local = Path(temporary) / "member.archive"
            with local.open("wb") as output:
                output.write(prefix)
                shutil.copyfileobj(stream, output)
            if local.stat().st_size != size:
                raise ValueError("Truncated archive member: " + name)
            with local.open("rb") as source_stream:
                kind = sniff(source_stream)
            source = {**origin, "member": name}
            if kind:
                consume(local, kind, source)
            elif DECLARED_CPG.search(name):
                receipt["errors"].append({"member": name,
                    "error": "Unsupported or invalid declared CPG archive format/schema"})
            elif depth < 3:
                child = inspect_archive(local, root, scratch, attempt_build=attempt_build,
                                        depth=depth + 1, origin=source, static_trust=static_trust)
                for key in ("packages", "online_recipes", "errors"):
                    receipt[key].extend(child[key])
                for key in ("nonpackage_members", "worker_excluded"):
                    receipt[key] += child[key]
            else:
                receipt["errors"].append({"member": name, "error": "Nested archive depth exceeds three"})

    with path.open("rb") as stream:
        kind = sniff(stream)
    if kind:
        consume(path, kind, origin)
    elif DECLARED_CPG.search(path.name):
        receipt["errors"].append({"member": origin.get("member", path.name),
            "error": "Unsupported or invalid declared CPG archive format/schema"})
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len({member.filename for member in members}) != len(members):
                raise ValueError("Duplicate ZIP member names")
            for member in members:
                if not member.is_dir():
                    with archive.open(member) as stream:
                        inspect_member(member.filename, member.file_size, stream)
    else:
        try:
            with open_outer_tar(path) as archive:
                names = set()
                for member in archive:
                    if member.name in names:
                        raise ValueError("Duplicate TAR member names")
                    names.add(member.name)
                    if member.isfile():
                        with archive.extractfile(member) as stream:
                            inspect_member(member.name, member.size, stream)
                    elif not member.isdir():
                        # Outer links are not followed or extracted.
                        receipt["nonpackage_members"] += 1
        except tarfile.ReadError as error:
            receipt["errors"].append({"member": origin.get("member", path.name),
                "error": "Invalid outer TAR container: " + str(error)})
    receipt["status"] = "inspected" if not receipt["errors"] else "inspected_with_failures"
    if depth == 0:
        write_json(root / "catalog" / "imports" / (checksum + ".json"), receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--framework", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--attempt-build", action="store_true")
    mode.add_argument("--static-trust", action="store_true")
    args = parser.parse_args()
    if args.framework:
        sys.path.insert(0, str(args.framework.resolve() / "src"))
    if WORKER.search(args.archive.name):
        parser.error("Worker-numbered deliveries are outside this migration")
    result = inspect_archive(args.archive, args.root, args.scratch, attempt_build=args.attempt_build, static_trust=args.static_trust)
    print(json.dumps({"archive": result["archive"], "status": result["status"],
                      "packages": len(result["packages"]), "online_recipes": len(result["online_recipes"]),
                      "errors": len(result["errors"]), "nonpackage_members": result["nonpackage_members"]}))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
