"""Unified, immutable resource selection and exact-byte accounting.

A selection is an intention, not an installation receipt. Metadata, acquired
bytes, installed files and host-qualified capabilities are different evidence
levels. Unknown quantities stay null; shared payloads are counted once only
when their byte identity is known.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
PRESETS = ("core", "open", "all", "custom")
ID = re.compile(r"[a-z0-9][a-z0-9.+_-]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _quantity(value: Any, field: str) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"{field} must be a nonnegative integer or null")


def _english(value: Any) -> None:
    if isinstance(value, str) and CJK.search(value):
        raise ValueError("Resource catalog and UI metadata must be in English")
    if isinstance(value, dict):
        for key, item in value.items():
            _english(key)
            _english(item)
    if isinstance(value, (list, tuple)):
        for item in value:
            _english(item)


def _strings(value: Any, field: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value) or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of nonempty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must not contain duplicates")
    return value


def _identifiers(values: Iterable[str], field: str) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field} must be an iterable of resource IDs, not a string")
    try:
        result = list(values)
    except TypeError as exc:
        raise ValueError(f"{field} must be an iterable of resource IDs") from exc
    if any(not isinstance(value, str) or not ID.fullmatch(value) for value in result):
        raise ValueError(f"{field} contains an invalid resource ID")
    return set(result)


def write_manifest(path: str | Path, manifest: Mapping[str, Any], *, overwrite: bool = False) -> None:
    """Publish complete JSON atomically; default never replaces existing work."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            if path.is_symlink():
                raise ValueError("Refusing to replace a symlink")
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Selection:
    preset: str
    requested_ids: tuple[str, ...]
    selected_ids: tuple[str, ...]
    required_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...] = ()


class Catalog:
    def __init__(self, value: Mapping[str, Any]):
        if not isinstance(value, Mapping):
            raise ValueError("A resource catalog must be a JSON object")
        self.value = copy.deepcopy(dict(value))
        if type(self.value.get("schema_version")) is not int or self.value["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Unsupported resource catalog schema")
        _english(self.value)
        self.resources = self.value.get("resources")
        if not isinstance(self.resources, list) or not self.resources:
            raise ValueError("A catalog needs a nonempty resource list")
        self.by_id: dict[str, dict[str, Any]] = {}
        for item in self.resources:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not ID.fullmatch(item["id"]):
                raise ValueError("Invalid resource identifier")
            name = item["id"]
            if name in self.by_id:
                raise ValueError(f"Duplicate resource: {name}")
            if not isinstance(item.get("title"), str) or not item["title"].strip():
                raise ValueError(f"Missing title: {name}")
            _strings(item.get("category"), f"{name}.category", nonempty=True)
            roles = _strings(item.get("roles"), f"{name}.roles", nonempty=True)
            if set(roles) - {"dev", "target", "host"}:
                raise ValueError(f"Invalid deployment roles: {name}")
            for field in ("archive_bytes", "source_logical_bytes", "installed_bytes", "installed_allocated_bytes"):
                _quantity(item.get(field), f"{name}.{field}")
            if item.get("sha256") is not None and (not isinstance(item["sha256"], str) or not SHA256.fullmatch(item["sha256"])):
                raise ValueError(f"Invalid SHA-256: {name}")
            if type(item.get("mandatory", False)) is not bool:
                raise ValueError(f"mandatory must be boolean: {name}")
            _strings(item.get("dependencies", []), f"{name}.dependencies")
            _strings(item.get("apt_dependency_ids", []), f"{name}.apt_dependency_ids")
            _strings(item.get("conflicts", []), f"{name}.conflicts")
            presets = _strings(item.get("presets", []), f"{name}.presets")
            if set(presets) - set(PRESETS):
                raise ValueError(f"Unknown preset membership: {name}")
            if "license_class" in item and (not isinstance(item["license_class"], str) or not item["license_class"].strip()):
                raise ValueError(f"Invalid license class: {name}")
            if "deployment" in item and not isinstance(item["deployment"], dict):
                raise ValueError(f"Deployment metadata must be an object: {name}")
            if item.get("payload_identity") is not None and (not isinstance(item["payload_identity"], str) or not item["payload_identity"].strip()):
                raise ValueError(f"Invalid payload identity: {name}")
            self.by_id[name] = item
        for item in self.resources:
            for dependency in item.get("dependencies", []):
                if dependency not in self.by_id:
                    raise ValueError(f"Missing dependency {dependency} for {item['id']}")
            for dependency in item.get("apt_dependency_ids", []):
                if dependency not in self.by_id or self.by_id[dependency].get("kind") != "apt":
                    raise ValueError(f"APT dependency {dependency} for {item['id']} must reference an existing apt resource")
            for conflict in item.get("conflicts", []):
                if conflict not in self.by_id:
                    raise ValueError(f"Missing conflict reference {conflict}")
        self._topological(set(self.by_id))
        self.sha256 = fingerprint(self.value)

    def _assert_intact(self) -> None:
        if self.resources is not self.value.get("resources") or fingerprint(self.value) != self.sha256:
            raise ValueError("Catalog changed after hashing; construct a new Catalog for changed resources")
        if set(self.by_id) != {item["id"] for item in self.resources} or any(
                self.by_id.get(item["id"]) is not item for item in self.resources):
            raise ValueError("Catalog resource index changed after validation")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Catalog":
        if path is None:
            module = Path(__file__).resolve()
            source_root = module.parents[2]
            source = source_root / "resources/catalog.json"
            checkout_layout = source_root / "src/compiler_playground" == module.parent
            path = source if checkout_layout and source.is_file() else module.with_name("resource_catalog.json")
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _topological(self, selected: set[str]) -> list[str]:
        complete: set[str] = set()
        active: set[str] = set()
        result: list[str] = []

        def visit(name: str) -> None:
            if name in active:
                raise ValueError(f"Dependency cycle at {name}")
            if name in complete:
                return
            active.add(name)
            for dependency in sorted(self.by_id[name].get("dependencies", [])):
                if dependency in selected:
                    visit(dependency)
            active.remove(name)
            complete.add(name)
            result.append(name)

        for name in sorted(selected):
            visit(name)
        return result

    def select(self, preset: str, include: Iterable[str] = (), exclude: Iterable[str] = ()) -> Selection:
        self._assert_intact()
        if preset not in PRESETS:
            raise ValueError(f"Unknown preset: {preset}")
        included, excluded = _identifiers(include, "include"), _identifiers(exclude, "exclude")
        for name in included | excluded:
            if name not in self.by_id:
                raise ValueError(f"Unknown resource: {name}")
        if included & excluded:
            raise ValueError("A resource cannot be both included and excluded")
        mandatory = {item["id"] for item in self.resources if item.get("mandatory", False)}
        if excluded & mandatory:
            raise ValueError("Mandatory resources cannot be excluded: " + ", ".join(sorted(excluded & mandatory)))
        requested = {item["id"] for item in self.resources
                     if preset != "custom" and (preset in item.get("presets", []) or preset == "all")}
        requested = (requested | included | mandatory) - excluded
        selected = set(requested)
        pending = list(selected)
        while pending:
            item = self.by_id[pending.pop()]
            for dependency in (*item.get("dependencies", []), *item.get("apt_dependency_ids", [])):
                if dependency in excluded:
                    raise ValueError(f"Excluded resource is required by the selection: {dependency}")
                if dependency not in selected:
                    selected.add(dependency)
                    pending.append(dependency)
        for name in selected:
            overlap = selected.intersection(self.by_id[name].get("conflicts", []))
            if overlap:
                raise ValueError(f"Conflicting resources: {name}, {', '.join(sorted(overlap))}")
        if preset == "open":
            closed = [name for name in selected if self.by_id[name].get("license_class") != "open"]
            if closed:
                raise ValueError("Open source preset cannot include restricted resources: " + ", ".join(sorted(closed)))
        required = mandatory | (selected - requested)
        return Selection(preset, tuple(sorted(requested)), tuple(self._topological(selected)),
                         tuple(sorted(required)), tuple(sorted(excluded)))

    def manifest(self, selection: Selection, local_payloads: Mapping[str, Any] | None = None,
                 configuration: Mapping[str, Any] | None = None) -> dict[str, Any]:
        # Validate preset semantics, canonical ordering and duplicates as well as
        # dependency closure; a re-labelled Open selection must not admit closed resources.
        if not isinstance(selection, Selection):
            raise ValueError("Expected a validated resource Selection")
        expected = self.select(selection.preset, include=selection.requested_ids, exclude=selection.excluded_ids)
        if selection != expected:
            raise ValueError("Selection preset or dependency closure is inconsistent")
        payloads = dict(local_payloads or {})
        if set(payloads) - set(selection.selected_ids):
            raise ValueError("Local payloads may only refer to selected resources")
        resources = []
        blockers = []
        for name in selection.selected_ids:
            item = copy.deepcopy(self.by_id[name])
            item["selection_required"] = name in selection.required_ids
            item["admission_status"] = "catalogued_not_acquired"
            if name in payloads:
                receipt = payloads[name]
                if not isinstance(receipt, dict) or receipt.get("resource_id") != name:
                    raise ValueError(f"Invalid local payload receipt for {name}")
                if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != SCHEMA_VERSION:
                    raise ValueError(f"Invalid local payload receipt schema for {name}")
                if not isinstance(receipt.get("sha256"), str) or not SHA256.fullmatch(receipt["sha256"]) or type(receipt.get("bytes")) is not int or receipt["bytes"] < 0:
                    raise ValueError(f"Local payload must have exact bytes and SHA-256: {name}")
                if receipt.get("catalog_sha256") != self.sha256:
                    raise ValueError(f"Local payload was admitted against a different catalog: {name}")
                if item.get("sha256") and receipt["sha256"] != item["sha256"]:
                    raise ValueError(f"Local payload SHA-256 differs from catalog: {name}")
                if item.get("archive_bytes") is not None and receipt["bytes"] != item["archive_bytes"]:
                    raise ValueError(f"Local payload size differs from catalog: {name}")
                evidence_sha = receipt.get("license_evidence_sha256")
                if evidence_sha is not None and (not isinstance(evidence_sha, str) or not SHA256.fullmatch(evidence_sha)):
                    raise ValueError(f"Invalid license evidence SHA-256 for {name}")
                if item.get("license_class") != "open" and evidence_sha is None:
                    raise ValueError(f"Restricted payload needs explicit license evidence: {name}")
                item.update(sha256=receipt["sha256"], archive_bytes=receipt["bytes"],
                            size_basis="measured_local_payload", local_payload=copy.deepcopy(receipt),
                            admission_status="local_bytes_recorded_not_installed")
            for reason in resource_blockers(item):
                blockers.append({"id": name, "reason": reason})
            resources.append(item)
        value = {"schema_version": SCHEMA_VERSION, "kind": "compiler_playground_resource_selection",
                 "catalog_sha256": self.sha256, "catalog_reviewed_on": self.value.get("reviewed_on"),
                 "selection": {"preset": selection.preset, "requested_ids": list(selection.requested_ids),
                               "selected_ids": list(selection.selected_ids), "required_ids": list(selection.required_ids),
                               "excluded_ids": list(selection.excluded_ids)},
                 "configuration": copy.deepcopy(dict(configuration or {})), "resources": resources,
                 "size_budget": size_budget(resources), "blockers": blockers,
                 "network_policy": "Normal networking. Provision selected resources before prepared trials.",
                 "qualified": False, "status": "selected_not_installed"}
        value["manifest_sha256"] = fingerprint(value)
        return value


def resource_blockers(item: Mapping[str, Any]) -> list[str]:
    blockers = []
    if item.get("kind") not in ("group", "virtual", "host"):
        if not item.get("version") or not item.get("immutable_ref"):
            blockers.append("Immutable version identity is unresolved")
        if item.get("archive_bytes") is None:
            blockers.append("Exact acquisition bytes are unresolved")
        if not item.get("sha256") and item.get("kind") not in ("apt", "oci"):
            blockers.append("Payload SHA-256 is unresolved")
    if not item.get("license_class"):
        blockers.append("License classification is unresolved")
    elif item.get("license_class") != "open" and not item.get("local_payload"):
        blockers.append("Local licensed payload and explicit license evidence are required")
    if item.get("kind") == "host":
        blockers.append("Host kernel, device and permission qualification is required")
    deployment = item.get("deployment", {})
    if deployment.get("adapter") in ("reference", "manual", "unresolved"):
        blockers.append("Reference material only; executable capability qualification is outstanding")
    return blockers


def size_budget(resources: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return unique known payload bytes and explicit incompleteness lists.

    The installed sum is attribution by resource, not total filesystem usage;
    only a filesystem/image measurement can establish that latter quantity.
    """
    resources = list(resources)
    known = 0
    source_known = 0
    installed_known = 0
    unknown: list[str] = []
    source_unknown: list[str] = []
    installed_unknown: list[str] = []
    seen: dict[str, int] = {}
    duplicates: list[dict[str, Any]] = []
    unique_without_identity: list[str] = []
    resource_ids: set[str] = set()
    for item in resources:
        name = str(item["id"])
        if name in resource_ids:
            raise ValueError(f"Duplicate resource in size budget: {name}")
        resource_ids.add(name)
        if item.get("kind") in ("group", "virtual", "host"):
            continue
        amount = item.get("archive_bytes")
        for field in ("archive_bytes", "source_logical_bytes", "installed_bytes"):
            _quantity(item.get(field), f"{name}.{field}")
        sha = item.get("sha256")
        if sha is not None and (not isinstance(sha, str) or not SHA256.fullmatch(sha)):
            raise ValueError(f"Invalid payload SHA-256: {name}")
        identity = ("sha256:" + str(sha)) if sha else item.get("payload_identity")
        if identity is not None and (not isinstance(identity, str) or not identity.strip()):
            raise ValueError(f"Invalid payload identity: {name}")
        if amount is None:
            unknown.append(name)
        elif identity:
            if identity in seen:
                if seen[identity] != amount:
                    raise ValueError(f"Conflicting sizes for one payload identity: {name}")
                duplicates.append({"id": name, "payload_identity": identity, "bytes": amount})
            else:
                known += amount
                seen[identity] = amount
        else:
            known += amount
            unique_without_identity.append(name)
        source_amount = item.get("source_logical_bytes")
        if source_amount is None:
            source_unknown.append(name)
        else:
            source_known += source_amount
        installed_amount = item.get("installed_bytes")
        if installed_amount is None:
            installed_unknown.append(name)
        else:
            installed_known += installed_amount
    return {"download_known_bytes": known, "download_unknown_ids": sorted(unknown),
            "download_without_content_identity_ids": sorted(unique_without_identity),
            "download_deduplicated_aliases": duplicates,
            "exact_download_total": known if not unknown and not unique_without_identity else None,
            "source_logical_known_bytes": source_known, "source_logical_unknown_ids": sorted(source_unknown),
            "installed_known_bytes": installed_known, "installed_unknown_ids": sorted(installed_unknown),
            "exact_installed_total": None,
            "build_peak_bytes": None, "oci_unique_compressed_layer_bytes": None,
            "note": "Download, source logical, installed logical, allocated blocks and peak build space are separate quantities. Installed total and peak require a measured deployment."}


def verify_manifest(value: Mapping[str, Any], catalog: Catalog | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("A selection manifest must be a JSON object")
    value = copy.deepcopy(dict(value))
    if type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA_VERSION or value.get("kind") != "compiler_playground_resource_selection":
        raise ValueError("Unsupported selection manifest")
    expected = value.pop("manifest_sha256", None)
    if expected != fingerprint(value):
        raise ValueError("Selection manifest fingerprint mismatch")
    value["manifest_sha256"] = expected
    if catalog is not None:
        if value.get("catalog_sha256") != catalog.sha256:
            raise ValueError("Selection manifest uses a different catalog")
        spec = value.get("selection")
        if not isinstance(spec, dict) or not isinstance(spec.get("preset"), str):
            raise ValueError("Invalid selection specification")
        for field in ("requested_ids", "selected_ids", "required_ids", "excluded_ids"):
            _strings(spec.get(field), "selection." + field)
        selection = Selection(spec["preset"], tuple(spec["requested_ids"]), tuple(spec["selected_ids"]),
                              tuple(spec["required_ids"]), tuple(spec["excluded_ids"]))
        if not isinstance(value.get("resources"), list) or any(
                not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in value["resources"]):
            raise ValueError("Invalid manifest resource records")
        local = {item["id"]: item["local_payload"] for item in value["resources"] if item.get("local_payload")}
        rebuilt = catalog.manifest(selection, local_payloads=local, configuration=value.get("configuration"))
        if rebuilt != value:
            raise ValueError("Selection manifest differs from its catalog-derived content")
    return value


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _measure_regular_file(path: Path, label: str) -> tuple[str, os.stat_result]:
    """Hash one stable regular inode and reject path replacement during the read."""
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode):
        raise ValueError(f"{label} must be a regular file, not a symlink or special file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or _file_identity(initial) != _file_identity(before):
            raise ValueError(f"{label} changed before measurement")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    current = path.lstat()
    if _file_identity(before) != _file_identity(after) or _file_identity(after) != _file_identity(current):
        raise ValueError(f"{label} changed during measurement")
    return digest, after


def import_payload(catalog: Catalog, resource_id: str, path: str | Path, *,
                   license_evidence: str | Path | None = None) -> dict[str, Any]:
    catalog._assert_intact()
    if resource_id not in catalog.by_id:
        raise ValueError("Unknown resource")
    resource = catalog.by_id[resource_id]
    path = Path(path).absolute()
    digest, after = _measure_regular_file(path, "Payload")
    if resource.get("sha256") and digest != resource["sha256"]:
        raise ValueError("Payload SHA-256 differs from catalog")
    if resource.get("archive_bytes") is not None and after.st_size != resource["archive_bytes"]:
        raise ValueError("Payload size differs from catalog")
    evidence_sha = None
    evidence_path = None
    if license_evidence is not None:
        evidence = Path(license_evidence).absolute()
        evidence_sha, _ = _measure_regular_file(evidence, "License evidence")
        evidence_path = str(evidence)
    if resource.get("license_class") != "open" and evidence_sha is None:
        raise ValueError("Explicit local license evidence is required for this payload")
    return {"schema_version": 1, "resource_id": resource_id, "catalog_sha256": catalog.sha256,
            "local_path": str(path), "sha256": digest, "bytes": after.st_size,
            "license_evidence_sha256": evidence_sha,
            "license_evidence_path": evidence_path,
            "license_acceptance": "user-supplied evidence" if evidence_sha else "not applicable",
            "status": "bytes_recorded_not_installed", "qualified": False}


def verify_payload_receipt(catalog: Catalog, receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Recheck current payload and license evidence before acquisition or deployment.

    A receipt is not a lock on a mutable pathname. Callers still need to use the
    verified bytes through their normal content-addressed publication process.
    """
    if not isinstance(receipt, Mapping) or receipt.get("catalog_sha256") != catalog.sha256:
        raise ValueError("Payload receipt uses a different catalog")
    if not isinstance(receipt.get("resource_id"), str) or not isinstance(receipt.get("local_path"), str):
        raise ValueError("Payload receipt needs a resource ID and local file path")
    fresh = import_payload(catalog, receipt["resource_id"], receipt["local_path"],
                           license_evidence=receipt.get("license_evidence_path"))
    if fresh != dict(receipt):
        raise ValueError("Payload receipt no longer matches the current payload or license evidence")
    return fresh


def measure_tree(path: str | Path) -> dict[str, Any]:
    """Measure a quiescent tree, including its root, without following links."""
    root = Path(path).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Measurement root must be a real directory")
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("Measurement root changed before measurement")
    logical = regular = links = 0
    allocated = root_info.st_blocks * 512
    directories = 1
    seen: set[tuple[int, int]] = {(root_info.st_dev, root_info.st_ino)}
    special: list[str] = []
    inventory: list[dict[str, Any]] = [{"path": ".", "kind": "directory",
                                       "allocated_bytes": allocated}]
    snapshots: list[tuple[Path, os.stat_result]] = [(root, root_info)]

    def walk_error(error: OSError) -> None:
        raise error

    for directory, names, files in os.walk(root, followlinks=False, onerror=walk_error):
        names.sort()
        files.sort()
        for name in sorted(names + files):
            item = Path(directory) / name
            info = item.lstat()
            snapshots.append((item, info))
            relative = item.relative_to(root).as_posix()
            identity = (info.st_dev, info.st_ino)
            duplicate = identity in seen
            if not duplicate:
                allocated += info.st_blocks * 512
                seen.add(identity)
            if stat.S_ISLNK(info.st_mode):
                links += 1
                inventory.append({"path": relative, "kind": "symlink", "target": os.readlink(item),
                                  "allocated_bytes": info.st_blocks * 512, "hardlink_duplicate": duplicate})
            elif stat.S_ISDIR(info.st_mode):
                directories += 1
                inventory.append({"path": relative, "kind": "directory",
                                  "allocated_bytes": info.st_blocks * 512})
            elif stat.S_ISREG(info.st_mode):
                regular += 1
                if not duplicate:
                    logical += info.st_size
                inventory.append({"path": relative, "kind": "file", "bytes": info.st_size,
                                  "allocated_bytes": info.st_blocks * 512, "hardlink_duplicate": duplicate})
            else:
                special.append(relative)
                inventory.append({"path": relative, "kind": "special", "mode": info.st_mode,
                                  "allocated_bytes": info.st_blocks * 512})
    for item, before in snapshots:
        after = item.lstat()
        if (_file_identity(before), before.st_mode, before.st_blocks) != (
                _file_identity(after), after.st_mode, after.st_blocks):
            raise ValueError("Tree changed during measurement: " + str(item))
    return {"schema_version": 1, "root": str(root), "logical_file_bytes": logical,
            "allocated_bytes": allocated, "regular_file_count": regular, "symlink_count": links,
            "directory_count": directories, "special_paths": special,
            "root_directory_included": True, "stable_during_scan": True,
            "file_size_inventory_sha256": fingerprint(inventory),
            "allocated_scope": "Unique-inode st_blocks * 512 attribution; shared reflink extents are not deduplicated.",
            "scope": "One quiescent filesystem tree including its root, no symlink traversal, hardlinks counted once; no OCI sharing or transient peak inferred."}


def export_budget_csv(path: str | Path, manifest: Mapping[str, Any]) -> None:
    fields = ("id", "title", "version", "immutable_ref", "roles", "license_class", "sha256",
              "archive_bytes", "source_logical_bytes", "installed_bytes", "size_basis", "admission_status")
    with Path(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in manifest["resources"]:
            writer.writerow({key: ";".join(item[key]) if key == "roles" else item.get(key)
                             for key in fields})
