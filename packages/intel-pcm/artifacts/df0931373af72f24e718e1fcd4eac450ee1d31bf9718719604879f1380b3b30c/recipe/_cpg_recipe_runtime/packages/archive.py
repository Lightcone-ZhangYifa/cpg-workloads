"""A small, content-verified resource package format for independent installs."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from collections import deque
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile

from ..resource_deploy import _publish_directory, relative_path
from ..resources import fingerprint, sha256_file
from .spec import DEFAULT_TARGET, IDENTIFIER, SHA256, validate_spec

FORMAT = "compiler_playground_resource_package"
METHODS = frozenset({"source", "binary", "material", "wrapper"})
PREFIX_OWNER_FILE = ".cpg-prefix.json"


def validate_prefix_owner(value, *, prefix=None):
    """Validate local installation ownership; this metadata is never payload."""
    if (not isinstance(value, dict) or set(value) != {"schema_version", "kind", "state", "prefix", "identity", "token"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["kind"] != "compiler_playground_prefix_ownership"
            or any(not isinstance(value[key], str) or "\0" in value[key]
                   or not Path(value[key]).is_absolute() for key in ("state", "prefix"))
            or not isinstance(value["identity"], str) or not SHA256.fullmatch(value["identity"])
            or not isinstance(value["token"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["token"])):
        raise ValueError("Invalid local package prefix ownership marker")
    if prefix is not None and Path(value["prefix"]).absolute() != Path(prefix).absolute():
        raise ValueError("Package prefix ownership marker belongs to a different location")
    return value


def validate_artifact_identity(value, *, require_sha256=True):
    """Validate an exact artifact reference shared by manifests and repositories."""
    if not isinstance(value, dict):
        raise ValueError("Artifact identity must be an object")
    if not isinstance(value.get("id"), str) or not IDENTIFIER.fullmatch(value["id"]):
        raise ValueError("Invalid artifact resource id")
    for key in ("version", "build"):
        if not isinstance(value.get(key), str) or not value[key].strip() or "\0" in value[key]:
            raise ValueError("Artifact " + key + " must be resolved explicitly")
    if value.get("method") not in METHODS:
        raise ValueError("Invalid artifact installation method")
    target = value.get("target")
    if not isinstance(target, dict) or any(not isinstance(target.get(key), str)
            or not target[key].strip() or "\0" in target[key] for key in DEFAULT_TARGET):
        raise ValueError("Artifact target must contain all explicit platform fields")
    if require_sha256 and (not isinstance(value.get("sha256"), str) or not SHA256.fullmatch(value["sha256"])):
        raise ValueError("Artifact SHA-256 must be resolved explicitly")
    return value


def validate_resolved_dependencies(value):
    """An artifact lock has one exact identity for each dependency resource ID."""
    if not isinstance(value, list):
        raise ValueError("Resolved dependencies must be a list")
    seen = set()
    for row in value:
        validate_artifact_identity(row)
        if row["id"] in seen:
            raise ValueError("Duplicate resolved dependency resource id: " + row["id"])
        seen.add(row["id"])
    return value


def _validate_dependency_coverage(spec, method, resolved):
    """A published binary must not resolve runtime resource versions implicitly.

    System dependencies retain their separate pinned-manager contract. Build-only
    dependencies are not needed to use an already-built binary. Source installs
    may still use explicit developer-supplied build/runtime path bindings.
    """
    if method == "binary":
        missing = set(spec["dependencies"]["run"]) - {row["id"] for row in resolved}
        if missing:
            raise ValueError("Binary runtime dependencies require exact artifact locks: "
                             + ", ".join(sorted(missing)))


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _unchanged_archive(path, stream, initial):
    try:
        current = path.lstat()
    except OSError as error:
        raise ValueError("Resource package changed while verifying") from error
    if (not stat.S_ISREG(current.st_mode) or _file_identity(current) != initial
            or _file_identity(os.fstat(stream.fileno())) != initial):
        raise ValueError("Resource package changed while verifying")


def _relative(value):
    path = relative_path(value)
    if path == PurePosixPath(".") or any(ord(char) < 32 for char in value):
        raise ValueError("A package entry must have a nonempty relative path")
    return path


def _link_target(target):
    if (not isinstance(target, str) or not target or PurePosixPath(target).is_absolute()
            or "\\" in target or any(ord(c) < 32 for c in target)):
        raise ValueError("Package symlinks must have relative targets")
    return target.split("/")


def _resolve_link(name, target, declared):
    """Resolve every directory link before '..', as the filesystem does.

    Each payload/recipe/tools tree must remain independently copyable. Merely
    being confined to the surrounding archive is insufficient for payloads.
    """
    pending = deque([*PurePosixPath(name).parent.parts, *_link_target(target)])
    resolved, links = [], 0
    namespace = name.split("/", 1)[0]
    while pending:
        part = pending.popleft()
        if part in {"", "."}:
            continue
        if part == "..":
            if len(resolved) <= 1:
                raise ValueError("Package symlink escapes its independent tree")
            resolved.pop()
            continue
        resolved.append(part)
        if resolved[0] != namespace:
            raise ValueError("Package symlink escapes its independent tree")
        path = "/".join(resolved)
        row = declared.get(path)
        if row is None:
            raise ValueError("Unresolved package symlink: " + name)
        if row["kind"] == "symlink":
            links += 1
            if links > 40:
                raise ValueError("Cyclic or excessively indirect package symlink")
            resolved.pop()
            pending.extendleft(reversed(_link_target(row["target"])))
        elif pending and row["kind"] != "directory":
            raise ValueError("Package symlink traverses a non-directory")
    return "/".join(resolved)


def _validate_contents(manifest, declared):
    method, spec = manifest["method"], manifest["package"]
    allowed = {"recipe", "tools"} | ({"sources"} if method == "source" else
              {"payload"} if method in {"binary", "material"} else set())
    if "payload/" + PREFIX_OWNER_FILE in declared:
        raise ValueError("A resource payload cannot carry local prefix ownership metadata")
    for name, row in declared.items():
        root = name.split("/", 1)[0]
        if root not in allowed or (name == root and row["kind"] != "directory"):
            raise ValueError("Package inventory contains an invalid top-level namespace")
        for parent in PurePosixPath(name).parents:
            if parent == PurePosixPath("."):
                continue
            if declared.get(parent.as_posix(), {}).get("kind") != "directory":
                raise ValueError("Package inventory must declare every parent directory")
    bindings = manifest.get("sources")
    if not isinstance(bindings, list):
        raise ValueError("Package source bindings must be a list")
    if method != "source":
        if bindings:
            raise ValueError("Only source packages may embed original source bindings")
        if method in {"binary", "material"} and declared.get("payload", {}).get("kind") != "directory":
            raise ValueError("A binary/material package must contain its payload directory")
        return
    expected = {source["id"]: source for source in spec["sources"]}
    if not expected or declared.get("sources", {}).get("kind") != "directory":
        raise ValueError("A source package must contain its declared original archives")
    actual, paths = {}, set()
    for binding in bindings:
        if not isinstance(binding, dict) or binding.get("id") not in expected or binding["id"] in actual:
            raise ValueError("Source package bindings must cover declared source IDs exactly once")
        source = expected[binding["id"]]
        if source["sha256"] is None or source["bytes"] is None:
            raise ValueError("Resolve source SHA-256 and byte count before packaging")
        path = _relative(binding.get("path")).as_posix()
        if path != "sources/" + source["sha256"]:
            raise ValueError("Embedded source paths must be content-addressed within sources/")
        row = declared.get(path, {})
        if row.get("kind") != "file" or row.get("sha256") != source["sha256"] or row.get("bytes") != source["bytes"]:
            raise ValueError("Embedded source inventory differs from its upstream lock")
        actual[binding["id"]] = binding
        paths.add(path)
    if set(actual) != set(expected):
        raise ValueError("A source package is missing a declared original archive")
    if {name for name in declared if name.startswith("sources/")} != paths:
        raise ValueError("A source package contains undeclared source archives")


def _python_cache(path):
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def inventory(root, *, exclude_python_cache=False):
    """Include files, directories and confined symlinks, without following them."""
    root = Path(root).resolve(strict=True)
    rows = []
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted([*directories, *files]):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if exclude_python_cache and _python_cache(Path(relative)):
                continue
            _relative(relative)
            info = path.lstat()
            row = {"path": relative, "mode": stat.S_IMODE(info.st_mode) & 0o777}
            if stat.S_ISREG(info.st_mode):
                row.update(kind="file", bytes=info.st_size, sha256=sha256_file(path))
            elif stat.S_ISDIR(info.st_mode):
                row.update(kind="directory")
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                _link_target(target)
                if not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError("Package link target escapes its source tree")
                row.update(kind="symlink", target=target)
            else:
                raise ValueError("Resource packages cannot contain devices, sockets or FIFOs")
            rows.append(row)
        directories[:] = sorted(name for name in directories if not (Path(directory) / name).is_symlink()
                                and not (exclude_python_cache and _python_cache(Path(name))))
    return sorted(rows, key=lambda row: row["path"])


def _copy(source, target, *, exclude_prefix_owner=False, exclude_python_cache=False):
    source = Path(source).resolve(strict=True)
    if source.is_dir():
        owner = source / PREFIX_OWNER_FILE
        excluded = set()
        if exclude_prefix_owner and (owner.exists() or owner.is_symlink()):
            if owner.is_symlink() or not owner.is_file():
                raise ValueError("Package prefix ownership must be an ordinary metadata file")
            validate_prefix_owner(json.loads(owner.read_text()), prefix=source)
            excluded.add(PREFIX_OWNER_FILE)
        def ignore(directory, names):
            ignored = excluded.copy() if Path(directory) == source else set()
            if exclude_python_cache:
                ignored.update(name for name in names if _python_cache(Path(name)))
            return ignored

        before = inventory(source, exclude_python_cache=exclude_python_cache)
        shutil.copytree(source, target, symlinks=True,
                        ignore=ignore)
        expected = [row for row in before if row["path"] not in excluded]
        if inventory(source, exclude_python_cache=exclude_python_cache) != before or inventory(target) != expected:
            raise ValueError("Package input changed while copying")
    elif source.is_file():
        target.mkdir()
        if exclude_python_cache and _python_cache(Path(source.name)):
            return
        before = (source.stat().st_size, sha256_file(source))
        shutil.copy2(source, target / source.name)
        if (source.stat().st_size, sha256_file(source)) != before or (
                (target / source.name).stat().st_size, sha256_file(target / source.name)) != before:
            raise ValueError("Package input changed while copying")
    else:
        raise ValueError("Package inputs must be ordinary files or directories")


def pack(spec, output, *, method, payload=None, sources=None, recipe_dir=None,
         tools_dir=None, prefix=None, relocatable=False, provenance=None,
         resolved_dependencies=()):
    """Create a deterministic archive from explicit local inputs.

    Source packages contain the original locked archives. Binary packages
    contain an installation tree; no installation or execution occurs here.
    A relocatable claim is a maintainer declaration, separately checked after
    each install. The default binary contract requires the original prefix.
    """
    spec = validate_spec(spec)
    if method not in METHODS:
        raise ValueError("Package method must be source, binary, material or wrapper")
    if not spec["version"]:
        raise ValueError("Resolve an exact resource version before packaging")
    if type(relocatable) is not bool:
        raise ValueError("relocatable must be boolean")
    resolved_dependencies = validate_resolved_dependencies(list(resolved_dependencies))
    _validate_dependency_coverage(spec, method, resolved_dependencies)
    if method in {"binary", "material"} and payload is None:
        raise ValueError("A binary/material package needs a payload tree")
    if method == "source" and (payload is not None or not spec["sources"]):
        raise ValueError("A source package needs declared original source payloads")
    if method != "source" and sources:
        raise ValueError("Only a source package may carry original source archives")
    if method == "wrapper" and (payload is not None or sources or not spec["recipe"].get("wrapper")):
        raise ValueError("A wrapper package must declare wrapper hooks and carry no payload or source archives")
    if method == "binary" and not relocatable and (not prefix or not Path(prefix).is_absolute()):
        raise ValueError("A fixed-prefix binary needs its absolute intended prefix")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cpg-pack-", dir=output.parent) as temporary:
        root = Path(temporary) / "tree"
        root.mkdir()
        declared_sources = []
        if method == "source":
            source_map = dict(sources or {})
            if set(source_map) != {source["id"] for source in spec["sources"]}:
                raise ValueError("Every declared source must be supplied exactly once")
            (root / "sources").mkdir()
            for source in spec["sources"]:
                path = Path(source_map[source["id"]])
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Source inputs must be regular archive files")
                if path.stat().st_size != source["bytes"] or sha256_file(path) != source["sha256"]:
                    raise ValueError("Source payload differs from its declared lock: " + source["id"])
                name = "sources/" + source["sha256"]
                if not (root / name).exists():
                    shutil.copy2(path, root / name)
                declared_sources.append({"id": source["id"], "path": name})
        elif method != "wrapper":
            _copy(payload, root / "payload", exclude_prefix_owner=True)
        for name, directory in (("recipe", recipe_dir), ("tools", tools_dir)):
            if directory is not None:
                # Match frozen recipe selection: interpreter-generated caches
                # are not authored inputs. Payload files remain unfiltered.
                _copy(directory, root / name, exclude_python_cache=True)
        rows = inventory(root)
        manifest = {"schema_version": 1, "kind": FORMAT, "package": spec,
            "method": method, "prefix_policy": {"kind": "relocatable" if relocatable or method != "binary" else "fixed", "prefix": str(prefix) if prefix else None},
            "sources": declared_sources, "resolved_dependencies": resolved_dependencies,
            "provenance": dict(provenance or {}), "files": rows,
            "inventory_sha256": fingerprint(rows)}
        manifest["manifest_sha256"] = fingerprint(manifest)
        raw = (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
        candidate = Path(temporary) / "package.tar.gz"
        with candidate.open("wb") as stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                info = tarfile.TarInfo("manifest.json")
                info.mode, info.size, info.mtime = 0o644, len(raw), 0
                archive.addfile(info, io.BytesIO(raw))
                for row in rows:
                    info = tarfile.TarInfo(row["path"])
                    info.mode, info.mtime = row["mode"], 0
                    if row["kind"] == "directory":
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    elif row["kind"] == "symlink":
                        info.type, info.linkname = tarfile.SYMTYPE, row["target"]
                        archive.addfile(info)
                    else:
                        info.size = row["bytes"]
                        with (root / row["path"]).open("rb") as source:
                            archive.addfile(info, source)
        verify_package(candidate)
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        os.link(candidate, output)
    return {"status": "created", "path": str(output), "bytes": output.stat().st_size,
            "sha256": sha256_file(output), "manifest_sha256": manifest["manifest_sha256"],
            "id": spec["id"], "version": spec["version"], "build": spec["build"], "method": method}


def verify_package(path, *, extract=None, expected_sha256=None, expected_bytes=None):
    """Verify every archive member before extracting to a fresh independent tree."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("A package must be a regular archive file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as compressed:
        original = os.fstat(compressed.fileno())
        if not stat.S_ISREG(original.st_mode):
            raise ValueError("A package must be a regular archive file")
        identity = _file_identity(original)
        checksum = hashlib.file_digest(compressed, "sha256").hexdigest()
        _unchanged_archive(path, compressed, identity)
        compressed.seek(0)
        if expected_sha256 is not None and checksum != expected_sha256:
            raise ValueError("Resource package SHA-256 mismatch")
        if expected_bytes is not None and original.st_size != expected_bytes:
            raise ValueError("Resource package byte count mismatch")
        with tarfile.open(fileobj=compressed, mode="r:gz") as archive:
            entries = archive.getmembers()
            names = [member.name for member in entries]
            if len(names) != len(set(names)) or names.count("manifest.json") != 1:
                raise ValueError("Duplicate package entry or missing manifest")
            # Duplicate names are rejected before building the lookup. Reuse
            # the parsed TarInfo objects; TarFile.getmember scans its full
            # member list on every call and becomes quadratic for large packs.
            members_by_name = {entry.name: entry for entry in entries}
            member = members_by_name["manifest.json"]
            if not member.isfile() or member.size > 64 * 1024 * 1024:
                raise ValueError("Invalid resource package manifest")
            manifest = json.load(archive.extractfile(member))
            if not isinstance(manifest, dict):
                raise ValueError("Resource package manifest must be an object")
            claimed = manifest.pop("manifest_sha256", None)
            if claimed != fingerprint(manifest):
                raise ValueError("Resource package manifest identity mismatch")
            manifest["manifest_sha256"] = claimed
            if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1 or manifest.get("kind") != FORMAT:
                raise ValueError("Unknown resource package format")
            validate_spec(manifest["package"])
            if manifest.get("method") not in METHODS:
                raise ValueError("Invalid package method")
            validate_resolved_dependencies(manifest.get("resolved_dependencies"))
            _validate_dependency_coverage(manifest["package"], manifest["method"], manifest["resolved_dependencies"])
            policy = manifest.get("prefix_policy", {})
            if policy.get("kind") not in {"fixed", "relocatable"} or (policy["kind"] == "fixed" and
                    (not isinstance(policy.get("prefix"), str) or not Path(policy["prefix"]).is_absolute())):
                raise ValueError("Invalid binary prefix policy")
            if manifest["method"] == "wrapper" and not manifest["package"]["recipe"].get("wrapper"):
                raise ValueError("Wrapper packages cannot contain a payload")
            rows = manifest.get("files")
            if not isinstance(rows, list):
                raise ValueError("Resource package inventory must be a list")
            if fingerprint(rows) != manifest.get("inventory_sha256"):
                raise ValueError("Resource package inventory mismatch")
            declared = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Package inventory entries must be objects")
                name = _relative(row["path"]).as_posix()
                if name in declared or name == "manifest.json" or type(row.get("mode")) is not int or not 0 <= row["mode"] <= 0o777:
                    raise ValueError("Invalid or duplicate package inventory entry")
                declared[name] = row
            if set(names) != set(declared) | {"manifest.json"}:
                raise ValueError("Package archive and inventory differ")
            _validate_contents(manifest, declared)
            for name, row in declared.items():
                for parent in PurePosixPath(name).parents:
                    if parent.as_posix() in declared and declared[parent.as_posix()]["kind"] != "directory":
                        raise ValueError("Package entry traverses a file or symlink")
                item = members_by_name[name]
                if item.mode != row["mode"] or item.islnk():
                    raise ValueError("Package mode mismatch or unsupported hardlink")
                if row["kind"] == "directory":
                    if not item.isdir():
                        raise ValueError("Package directory type mismatch")
                elif row["kind"] == "symlink":
                    if not item.issym() or item.linkname != row["target"]:
                        raise ValueError("Package symlink identity mismatch")
                    _resolve_link(name, row["target"], declared)
                elif row["kind"] == "file":
                    if (not item.isfile() or type(row.get("bytes")) is not int or row["bytes"] < 0
                            or item.size != row["bytes"] or not isinstance(row.get("sha256"), str)
                            or not SHA256.fullmatch(row["sha256"])):
                        raise ValueError("Package file type or size mismatch")
                    with archive.extractfile(item) as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                            raise ValueError("Package file SHA-256 mismatch: " + name)
                else:
                    raise ValueError("Invalid package file type")
            _unchanged_archive(path, compressed, identity)
            if extract is not None:
                destination = Path(extract).absolute()
                if destination.exists() or destination.is_symlink():
                    raise FileExistsError(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix=".cpg-unpack-", dir=destination.parent))
                try:
                    for row in rows:
                        target = staging / row["path"]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if row["kind"] == "directory":
                            target.mkdir(exist_ok=True)
                        elif row["kind"] == "file":
                            with archive.extractfile(members_by_name[row["path"].rstrip("/")]) as source, target.open("xb") as output:
                                shutil.copyfileobj(source, output)
                            target.chmod(row["mode"])
                    for row in rows:
                        if row["kind"] == "symlink":
                            (staging / row["path"]).symlink_to(row["target"])
                    for row in sorted(rows, key=lambda row: row["path"].count("/"), reverse=True):
                        if row["kind"] == "directory":
                            (staging / row["path"]).chmod(row["mode"])
                    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                    (staging / "manifest.json").chmod(0o644)
                    if inventory(staging) != sorted([*rows, {"path": "manifest.json", "kind": "file", "mode": 0o644, "bytes": (staging / "manifest.json").stat().st_size, "sha256": sha256_file(staging / "manifest.json")}], key=lambda row: row["path"]):
                        raise ValueError("Extracted package does not match its inventory")
                    _unchanged_archive(path, compressed, identity)
                    _publish_directory(staging, destination)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
    return {"status": "verified", "path": str(path.absolute()), "sha256": checksum,
            "bytes": original.st_size, "manifest": manifest}
