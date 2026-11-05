"""Compile a selected resource manifest into a deterministic preparation plan.

No downloads happen while selecting, planning, or measuring. Acquisition is an
explicit initialization operation. Build recipes are trusted project inputs;
they run only inside the development image, never on the target runtime host.
"""
from __future__ import annotations

import copy
import ctypes
import errno
import fcntl
import hashlib
from http.client import HTTPException
from importlib.resources import as_file, files
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from typing import Any, Mapping

from ._util import atomic_json
from .resources import Catalog, SHA256, fingerprint, sha256_file, verify_manifest, write_manifest

SAFE_PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_:~=-]*\Z")


def recipe_helper_names(rows: list[Mapping[str, Any]]) -> list[str]:
    """Find explicit project helper arguments without interpreting shell text."""
    names = set()

    def visit(value: Any, resource_id: str) -> None:
        if isinstance(value, Mapping):
            for child in value.values():
                visit(child, resource_id)
        elif isinstance(value, list):
            for child in value:
                visit(child, resource_id)
        elif isinstance(value, str) and "{tools}" in value:
            match = re.fullmatch(r"\{tools\}/([A-Za-z0-9][A-Za-z0-9_.-]*)", value)
            if not match:
                raise ValueError("Recipe helpers require a complete explicit {tools}/filename argument")
            names.add(match.group(1))
        elif isinstance(value, str) and "{recipe}" in value:
            match = re.fullmatch(r"\{recipe\}/([A-Za-z0-9][A-Za-z0-9_./-]*)", value)
            if not match or not re.fullmatch(r"[a-z0-9][a-z0-9.+_-]*", resource_id):
                raise ValueError("Package helpers require a complete explicit {recipe}/relative-file argument")
            relative_path(match.group(1))
            names.add("@package/" + resource_id + "/" + match.group(1))

    for row in rows:
        visit(row.get("deployment", {}), row.get("id", ""))
    return sorted(names)


def recipe_helper_hashes(rows: list[Mapping[str, Any]], tools_directory: Path | None) -> dict[str, str]:
    """Bind every referenced helper to regular local bytes before admission."""
    names = recipe_helper_names(rows)
    if names and tools_directory is None:
        raise ValueError("Selected recipes use project helpers; supply their tools_directory for admission")
    result = {}
    for name in names:
        path = Path(tools_directory).parent / recipe_helper_relative_path(name)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Recipe helper is not an available regular file: " + name)
        result[name] = sha256_file(path)
    return result


def recipe_helper_relative_path(name: str) -> str:
    """Map an admitted helper key to its maintained project-relative path."""
    if name.startswith("@package/"):
        resource_id, filename = name[len("@package/"):].split("/", 1)
        if not re.fullmatch(r"[a-z0-9][a-z0-9.+_-]*", resource_id):
            raise ValueError("Invalid package helper resource ID")
        return "resources/packages/" + resource_id + "/recipe/" + relative_path(filename).as_posix()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("Invalid shared recipe helper filename")
    return "tools/" + name


def _publish_directory(source: Path, destination: Path) -> None:
    """Atomically publish a tree without replacing any concurrent destination.

    This release targets Linux. A plain rename can replace an empty directory,
    so an existence check followed by rename is insufficient for immutability.
    Unsupported kernels or filesystems must fail instead of weakening the gate.
    """
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    if rename is None:
        raise OSError(errno.ENOTSUP, "Atomic immutable directory publication requires Linux renameat2")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
            raise OSError(error, "Filesystem lacks immutable renameat2 publication", str(destination))
        raise OSError(error, os.strerror(error), str(destination))
    descriptor = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or any(c in value for c in ("\\", "\x00", "\n", "\r")):
        raise ValueError("Invalid relative resource path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Resource path must be canonical and relative")
    return path


def _material_paths(materials: list[Mapping[str, Any]]) -> dict[str, PurePosixPath]:
    """Validate the whole namespace before copying or downloading any payload."""
    by_id: dict[str, PurePosixPath] = {}
    by_path: dict[PurePosixPath, str] = {}
    for item in materials:
        name = item["id"]
        path = relative_path(item.get("material_path") or "payloads/" + name)
        if name in by_id:
            raise ValueError("Duplicate material identifier: " + name)
        if path == PurePosixPath(".") or path == PurePosixPath("materialization.json"):
            raise ValueError("Reserved material destination: " + str(path))
        if path in by_path:
            raise ValueError(f"Conflicting material paths: {name} and {by_path[path]} use {path}")
        by_id[name], by_path[path] = path, name
    for path, name in by_path.items():
        for ancestor in path.parents:
            if ancestor in by_path:
                raise ValueError(f"Conflicting material ancestor paths: {name} and {by_path[ancestor]}")
    return by_id


def _verify_file(path: Path, expected: Mapping[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular payload: {path}")
    if expected.get("archive_bytes") is not None and path.stat().st_size != expected["archive_bytes"]:
        raise ValueError(f"Payload byte count mismatch: {expected['id']}")
    if not SHA256.fullmatch(str(expected.get("sha256", ""))):
        raise ValueError(f"No accepted SHA-256 for {expected['id']}")
    if sha256_file(path) != expected["sha256"]:
        raise ValueError(f"Payload SHA-256 mismatch: {expected['id']}")


def acquire_file(item: Mapping[str, Any], cache: str | Path, *, receipt: dict | None = None) -> Path:
    """Serialize acquisition per digest while unrelated downloads can proceed."""
    if receipt is not None:
        # Initialize this request before any admission or network failure. A
        # reused receipt must never retain another resource's successful path.
        for key in ("status", "origin", "path", "sha256", "bytes", "integrity",
                    "source_url", "attempts", "resolved_url"):
            receipt.pop(key, None)
        receipt.update(status="not_run", origin=None, integrity="not_run",
                       source_url=item.get("source_url") or item.get("url"),
                       sha256=item.get("sha256"), bytes=item.get("archive_bytes"))
    checksum = str(item.get("sha256", ""))
    if not SHA256.fullmatch(checksum):
        raise ValueError(f"Resolve payload SHA-256 before acquisition: {item['id']}")
    cache = Path(cache)
    locks = cache / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(locks / (checksum + ".lock"),
                         os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return _acquire_file_locked(item, cache) if receipt is None else _acquire_file_locked(item, cache, receipt=receipt)
    finally:
        os.close(descriptor)


def _download_urls(item: Mapping[str, Any], original: str) -> list[str]:
    """Keep the admitted identity and add only maintained, exact-byte mirrors.

    Original catalog facts stay unchanged. This small repair table contains
    observed upstream moves, not a repository resolver or version selector.
    """
    document = json.loads(files("compiler_playground").joinpath("resource_input_mirrors.json").read_text())
    urls = [original]
    for row in document["mirrors"]:
        if (row["original_url"] == original and row["sha256"] == item["sha256"]
                and row["bytes"] == item["archive_bytes"]):
            for url in row["urls"]:
                if not isinstance(url, str) or not url.startswith("https://"):
                    raise ValueError("Maintained input mirrors require HTTPS")
                if url not in urls:
                    urls.append(url)
    return urls


def _acquire_file_locked(item: Mapping[str, Any], cache: str | Path, *, receipt: dict | None = None) -> Path:
    """Acquire exactly one admitted payload; never publish a partial response."""
    if not SHA256.fullmatch(str(item.get("sha256", ""))):
        raise ValueError(f"Resolve payload SHA-256 before acquisition: {item['id']}")
    if type(item.get("archive_bytes")) is not int or item["archive_bytes"] < 0:
        raise ValueError(f"Resolve exact payload bytes before acquisition: {item['id']}")
    # A cached byte sequence is not a reusable license admission. Entitlement
    # evidence belongs to this resource and must still be present on every use.
    if item.get("license_class") != "open":
        local = item.get("local_payload")
        if not isinstance(local, Mapping):
            raise ValueError("Restricted payloads must be imported with local license evidence")
        evidence = local.get("license_evidence_path")
        evidence_sha = local.get("license_evidence_sha256")
        if (not isinstance(evidence, str) or not evidence
                or not isinstance(evidence_sha, str) or not SHA256.fullmatch(evidence_sha)
                or Path(evidence).is_symlink() or not Path(evidence).is_file()
                or sha256_file(evidence) != evidence_sha):
            raise ValueError("Local license evidence changed or is unavailable")
    cache = Path(cache)
    directory = cache / "sha256" / item["sha256"][:2]
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / item["sha256"]
    origin = "local_import" if item.get("local_payload") else "bundled" if item.get("bundled_path") else "https_download"
    def verify(path, source_origin):
        if receipt is not None:
            receipt.update(status="acquired", origin=source_origin, path=str(path.absolute()),
                           sha256=item["sha256"], bytes=item["archive_bytes"], integrity="not_run",
                           source_url=item.get("source_url") or item.get("url"))
        try:
            _verify_file(path, item)
        except BaseException:
            if receipt is not None:
                receipt["integrity"] = "failed"
            raise
    def observed(origin):
        if receipt is not None:
            receipt.update(status="acquired", origin=origin, path=str(destination.absolute()),
                           sha256=item["sha256"], bytes=item["archive_bytes"], integrity="verified",
                           source_url=item.get("source_url") or item.get("url"))
    if destination.exists() or destination.is_symlink():
        verify(destination, "cache")
        observed("cache")
        return destination
    descriptor, name = tempfile.mkstemp(prefix=".partial-", dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            if item.get("local_payload"):
                source = Path(item["local_payload"]["local_path"])
                verify(source, origin)
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, output, length=1024 * 1024)
            elif item.get("bundled_path"):
                source = Path(item["bundled_path"])
                verify(source, origin)
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, output, length=1024 * 1024)
            else:
                url = item.get("source_url") or item.get("url")
                if not isinstance(url, str) or not url.startswith("https://"):
                    raise ValueError(f"An HTTPS URL or admitted local payload is required: {item['id']}")
                urls = _download_urls(item, url)
                if receipt is not None:
                    receipt["attempts"] = []
                for index, candidate in enumerate(urls):
                    attempt = {"url": candidate, "status": "started"}
                    if receipt is not None:
                        receipt["attempts"].append(attempt)
                    # A failed or partial response must never prefix the retry.
                    output.seek(0)
                    output.truncate()
                    try:
                        request = urllib.request.Request(candidate, headers={"User-Agent": "compiler-playground-admission/0.5.0"})
                        with urllib.request.urlopen(request, timeout=90) as stream:
                            resolved = stream.geturl()
                            if not resolved.startswith("https://"):
                                raise ValueError("Payload redirected to an insecure transport")
                            shutil.copyfileobj(stream, output, length=1024 * 1024)
                        output.flush()
                        _verify_file(temporary, item)
                    except (OSError, ValueError, HTTPException) as error:
                        attempt.update(status="failed", error_type=type(error).__name__, error=str(error))
                        if index + 1 == len(urls):
                            if receipt is not None:
                                receipt.update(status="failed", origin=origin, integrity="failed" if isinstance(error, ValueError) else "not_run")
                            raise
                    else:
                        attempt.update(status="verified", resolved_url=resolved)
                        if receipt is not None:
                            receipt["resolved_url"] = resolved
                        break
            output.flush()
            os.fsync(output.fileno())
        verify(temporary, origin)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            _verify_file(destination, item)
        observed(origin)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def unpack_archive(archive: str | Path, destination: str | Path, *, strip_root: bool = True) -> None:
    """Extract reviewed archives with traversal, device and link checks.

    An archive suffix is not needed: content-addressed cache files have no
    extension. Extraction is staged on the destination filesystem.
    """
    archive, destination = Path(archive), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".unpack-", dir=destination.parent))
    tree = temporary / "tree"
    tree.mkdir()
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as source:
                seen: set[str] = set()
                for entry in source.infolist():
                    path = relative_path(entry.filename.rstrip("/"))
                    if path.as_posix() in seen:
                        raise ValueError("Duplicate ZIP member")
                    seen.add(path.as_posix())
                    mode = (entry.external_attr >> 16) & 0o170000
                    if mode not in (0, 0o100000, 0o040000):
                        raise ValueError("ZIP special files and links are not accepted")
                    target = tree.joinpath(*path.parts)
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with source.open(entry) as reader, target.open("xb") as writer:
                            shutil.copyfileobj(reader, writer)
                        target.chmod(0o755 if (entry.external_attr >> 16) & 0o111 else 0o644)
        else:
            with tarfile.open(archive, "r:*") as source:
                entries = source.getmembers()
                seen = set()
                for entry in entries:
                    name = entry.name.rstrip("/")
                    while name.startswith("./"):
                        name = name[2:]
                    if name in ("", ".") and entry.isdir():
                        continue
                    path = relative_path(name)
                    if name in seen:
                        raise ValueError("Duplicate TAR member")
                    seen.add(name)
                    if not (entry.isfile() or entry.isdir() or entry.issym() or entry.islnk()):
                        raise ValueError("Archive special files are not accepted")
                    if entry.issym() or entry.islnk():
                        link = PurePosixPath(entry.linkname)
                        if link.is_absolute() or "\\" in entry.linkname:
                            raise ValueError("Absolute archive link")
                        base = tree.joinpath(*path.parts).parent if entry.issym() else tree
                        if not (base / entry.linkname).resolve().is_relative_to(tree.resolve()):
                            raise ValueError("Archive link escapes extraction root")
                # Python's data filter also rejects extraction through symlinks.
                if not hasattr(tarfile, "data_filter"):
                    raise ValueError("Secure TAR extraction needs Python with tarfile.data_filter")
                source.extractall(tree, filter="data")
        children = list(tree.iterdir())
        source_tree = children[0] if strip_root and len(children) == 1 and children[0].is_dir() and not children[0].is_symlink() else tree
        # Stripping an enclosing directory changes the allowed link boundary.
        # Check the tree that will actually be published, including links that
        # leave and re-enter the old root by name and break after relocation.
        for directory, directories, filenames in os.walk(source_tree, followlinks=False):
            for name in directories + filenames:
                entry = Path(directory) / name
                if not entry.is_symlink():
                    continue
                link = PurePosixPath(os.readlink(entry))
                relative_parts = list(entry.parent.relative_to(source_tree).parts)
                for part in link.parts:
                    if part == "..":
                        if not relative_parts:
                            raise ValueError("Archive link escapes the published root")
                        relative_parts.pop()
                    elif part != ".":
                        relative_parts.append(part)
                try:
                    contained = entry.resolve().is_relative_to(source_tree.resolve())
                except (OSError, RuntimeError) as error:
                    raise ValueError("Archive link cannot be resolved safely") from error
                if not contained:
                    raise ValueError("Archive link escapes the published root")
        _publish_directory(source_tree, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def preparation_plan(manifest: Mapping[str, Any], *, catalog: Catalog | None = None) -> dict[str, Any]:
    manifest = verify_manifest(manifest, catalog)
    packages: dict[str, set[str]] = {"dev": set(), "target": set()}
    wheels: dict[str, dict[str, str]] = {}
    materials, recipes, host, blocked = [], [], [], []
    for item in manifest["resources"]:
        deployment = item.get("deployment", {})
        adapter = deployment.get("adapter", "reference")
        if item.get("kind") == "apt":
            name = item.get("package_name")
            version = item.get("version")
            if not name or not version or not SAFE_PACKAGE.fullmatch(name + "=" + version):
                blocked.append({"id": item["id"], "reason": "APT exact version is unresolved"})
            else:
                for role in item["roles"]:
                    if role in packages:
                        packages[role].add(name + "=" + version)
                materials.append(item)
        elif item.get("kind") == "wheel":
            name, version, sha = item.get("package_name"), item.get("version"), item.get("sha256")
            if not name or not version or not sha:
                blocked.append({"id": item["id"], "reason": "Wheel identity is unresolved"})
            else:
                environment = deployment.get("environment", "research")
                normalized_name = re.sub(r"[-_.]+", "-", name).lower()
                requirement = normalized_name + "==" + version + " --hash=sha256:" + sha
                entries = wheels.setdefault(environment, {})
                if normalized_name in entries and entries[normalized_name] != requirement:
                    raise ValueError(f"Conflicting wheel identities in environment {environment}: {normalized_name}")
                entries[normalized_name] = requirement
                materials.append(item)
        elif item.get("kind") in ("host", "group", "virtual", "oci"):
            if item.get("kind") == "host":
                host.append(item["id"])
        else:
            if not item.get("sha256") or item.get("archive_bytes") is None:
                blocked.append({"id": item["id"], "reason": "Exact payload hash/bytes must be resolved or imported"})
            elif item.get("license_class", "open") != "open" and not item.get("local_payload"):
                blocked.append({"id": item["id"], "reason": "Licensed payload must be imported explicitly"})
            else:
                materials.append(item)
        for role, names in deployment.get("apt_dependencies", {}).items():
            if role not in packages:
                continue
            for name in names:
                # Every recipe package must be represented by an exact catalog
                # record, so changing an optional capability changes its lock.
                matches = [entry for entry in manifest["resources"] if entry.get("kind") == "apt" and entry.get("package_name") == name]
                if not matches:
                    blocked.append({"id": item["id"], "reason": f"Missing selected APT dependency: {name}"})
                else:
                    for match in matches:
                        packages[role].add(name + "=" + match["version"])
        if deployment.get("submodule_closure_complete") is False or deployment.get("lfs_closure_complete") is False:
            blocked.append({"id": item["id"], "reason": "Source archive lacks the pinned recursive submodule or LFS closure"})
        if deployment.get("unavailable_apt_dependencies"):
            blocked.append({"id": item["id"], "reason": "Unresolved system dependency: " + ", ".join(deployment["unavailable_apt_dependencies"])})
        if item.get("archive_incomplete_for_build"):
            blocked.append({"id": item["id"], "reason": "The source archive omits required build/test files"})
        if adapter in ("cmake", "make", "copy", "commands", "vendor-local"):
            recipes.append({"id": item["id"], "source_id": item["id"], "deployment": copy.deepcopy(deployment),
                            "roles": item["roles"], "qualified": False})
    # APT package cycles are legitimate and handled as a separate closure graph.
    apt_rows = {r["id"]: r for r in manifest["resources"] if r.get("kind") == "apt"}
    for role in packages:
        pending = [r for r in apt_rows.values() if r["package_name"] + "=" + r["version"] in packages[role]]
        seen = set()
        while pending:
            row = pending.pop()
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            packages[role].add(row["package_name"] + "=" + row["version"])
            for dependency in row.get("apt_dependency_ids", []):
                if dependency in apt_rows:
                    pending.append(apt_rows[dependency])
                else:
                    blocked.append({"id": row["id"], "reason": "Missing selected APT closure package: " + dependency})
    _material_paths(materials)
    plan = {"schema_version": 1, "kind": "compiler_playground_preparation_plan",
            "selection_manifest_sha256": manifest["manifest_sha256"],
            "catalog_sha256": manifest["catalog_sha256"],
            "apt": {role: sorted(names) for role, names in packages.items()},
            "wheel_environments": {name: [entries[k] for k in sorted(entries)] for name, entries in sorted(wheels.items())},
            "materials": materials, "recipes": recipes, "host_qualification_ids": sorted(host),
            "blockers": blocked, "qualified": False,
            "network_policy": manifest["network_policy"],
            "selection": manifest["selection"],
            "configuration": manifest["configuration"],
            "base_image": next((r["immutable_ref"] for r in manifest["resources"] if r["id"] == "ubuntu-base"), None),
            "compatibility_label": "extended" if any(r.get("license_class", "open") != "open" for r in manifest["resources"]) else "open",
            "compatibility_note": "Legacy edition label is derived metadata only. One catalog and one selected manifest are maintained."}
    plan["plan_sha256"] = fingerprint(plan)
    return plan


def selected_recipe_manifest(manifest: Mapping[str, Any], plan: Mapping[str, Any], *,
                             tools_directory: Path | None = None) -> dict[str, Any]:
    """Bind executable recipe inputs to the exact selection and preparation plan."""
    verified = verify_manifest(manifest)
    unsealed = copy.deepcopy(dict(plan))
    digest = unsealed.pop("plan_sha256", None)
    if digest != fingerprint(unsealed):
        raise ValueError("Preparation plan fingerprint mismatch")
    if (plan.get("selection_manifest_sha256") != verified["manifest_sha256"]
            or plan.get("catalog_sha256") != verified["catalog_sha256"]):
        raise ValueError("Preparation plan belongs to a different resource selection")
    value = {"schema_version": 1, "catalog_sha256": verified["catalog_sha256"],
             "selection_manifest_sha256": verified["manifest_sha256"],
             "preparation_plan_sha256": digest, "resources": copy.deepcopy(verified["resources"]),
             "helper_sha256": recipe_helper_hashes(verified["resources"], tools_directory)}
    value["recipes_sha256"] = fingerprint(value)
    return value


def stage_plan(directory: str | Path, manifest: Mapping[str, Any], *, catalog: Catalog | None = None) -> dict[str, Any]:
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(directory)
    plan = preparation_plan(manifest, catalog=catalog)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".resource-plan-", dir=directory.parent))
    try:
        write_manifest(staging / "selection.json", manifest)
        write_manifest(staging / "plan.json", plan)
        for role, packages in plan["apt"].items():
            (staging / f"apt-{role}.txt").write_text("\n".join(packages) + "\n", encoding="utf-8")
        for environment, requirements in plan["wheel_environments"].items():
            if not re.fullmatch(r"[a-z0-9_-]+", environment):
                raise ValueError("Invalid wheel environment name")
            (staging / f"python-{environment}.lock").write_text("\n".join(requirements) + "\n", encoding="utf-8")
        write_manifest(staging / "recipes.json", {"schema_version": 1, "recipes": plan["recipes"]})
        _publish_directory(staging, directory)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"path": str(directory), "plan_sha256": plan["plan_sha256"], "blockers": plan["blockers"], "qualified": False}


def materialize(plan: Mapping[str, Any], cache: str | Path, output: str | Path,
                *, project_root: str | Path | None = None,
                report_path: str | Path | None = None) -> dict[str, Any]:
    plan = copy.deepcopy(dict(plan))
    claimed = plan.pop("plan_sha256", None)
    if claimed != fingerprint(plan):
        raise ValueError("Preparation plan fingerprint mismatch")
    plan["plan_sha256"] = claimed
    if plan["blockers"]:
        raise ValueError("Preparation plan has unresolved blockers; resolve them before acquisition")
    material_paths = _material_paths(plan["materials"])
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".materialize-", dir=output.parent))
    receipt = []
    progress = {"schema_version": 1, "kind": "compiler_playground_resource_acquisition",
                "plan_sha256": claimed, "status": "running", "resources": [
                    {"id": item["id"], "status": "not_run", "acquisition": {"status": "not_run", "integrity": "not_run"}}
                    for item in plan["materials"]]}
    def publish_progress():
        if report_path is not None:
            atomic_json(Path(report_path), progress)
    publish_progress()
    current = None
    try:
        for index, entry in enumerate(plan["materials"]):
            current = progress["resources"][index]
            acquired = current["acquisition"]
            item = copy.deepcopy(entry)
            if item.get("bundled_path"):
                relative = relative_path(item["bundled_path"])
                if project_root is not None:
                    item["bundled_path"] = str(Path(project_root) / item["bundled_path"])
                    source = acquire_file(item, cache, receipt=acquired)
                else:
                    bundled = files("compiler_playground").joinpath("_support", *relative.parts)
                    if not bundled.is_file():
                        raise ValueError("Bundled resources require a project root or a file supplied by the installed package")
                    with as_file(bundled) as packaged:
                        item["bundled_path"] = str(packaged)
                        source = acquire_file(item, cache, receipt=acquired)
            else:
                source = acquire_file(item, cache, receipt=acquired)
            publish_progress()
            target_rel = material_paths[item["id"]].as_posix()
            target = staging.joinpath(*material_paths[item["id"]].parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.get("extract", False):
                unpack_archive(source, target, strip_root=item.get("strip_archive_root", True))
            else:
                shutil.copy2(source, target)
            receipt.append({"id": item["id"], "path": target_rel, "sha256": item["sha256"],
                            "archive_bytes": item["archive_bytes"], "extracted": bool(item.get("extract")),
                            "status": "materialized_not_built", "acquisition": copy.deepcopy(acquired)})
            current["status"] = "materialized_not_built"
            publish_progress()
        # Exact supplementary artifacts (notably notices and submodule trees)
        # are installed only after all primary source trees are present.
        for entry in plan["materials"]:
            current = next(row for row in progress["resources"] if row["id"] == entry["id"])
            target_rel = entry.get("supplement_to")
            if not target_rel:
                continue
            source = staging.joinpath(*relative_path(entry["material_path"]).parts)
            target = staging.joinpath(*relative_path(target_rel).parts)
            if not target.resolve().is_relative_to(staging.resolve()):
                raise ValueError("Supplement destination escapes materialization root: " + target_rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink() and not list(target.iterdir()):
                    target.rmdir()
                else:
                    raise ValueError("Supplement would replace existing source content: " + target_rel)
            if source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target)
        result = {"schema_version": 1, "plan_sha256": claimed, "resources": receipt,
                  "qualified": False, "status": "materialized_not_built"}
        write_manifest(staging / "materialization.json", result)
        _publish_directory(staging, output)
        progress["status"] = "completed"
        publish_progress()
        return result
    except BaseException as error:
        progress.update(status="failed", error=str(error))
        if current is not None:
            current.update(status="failed", error=str(error))
            if current["acquisition"]["status"] != "acquired":
                current["acquisition"].update(status="failed", reason=str(error))
        publish_progress()
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
