"""Small, explicit resource-package definitions and lossless catalog migration."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
import shlex
from typing import Any, Mapping

from .checks import classify_legacy_check

SCHEMA_VERSION = 1
PROVIDERS = frozenset({"apt", "python", "source", "binary", "material", "component", "meta", "host"})
DEFAULT_TARGET = {"os": "linux", "arch": "x86_64", "distribution": "ubuntu", "distribution_version": "24.04"}
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9.+_-]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _string(value, field, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError(f"{field} must be a nonempty NUL-free string")


def _strings(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    for item in value:
        _string(item, field)


def _relative(value, field, *, nullable=False):
    if nullable and value is None:
        return
    _string(value, field)
    path = PurePosixPath(value)
    if (path == PurePosixPath(".") or path.is_absolute() or ".." in path.parts or path.as_posix() != value
            or "\\" in value or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{field} must be a canonical relative path")


def _identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {field}")


def _command(value, field):
    _strings(value, field)
    if not value:
        raise ValueError(f"{field} must contain an executable")


def validate_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy a definition; unknown source identities remain unknown.

    A valid definition is inspectable, not necessarily preparable or installed.
    ``preparation_blockers`` reports missing acquisition/build inputs separately.
    The complete original catalog record is a generated compatibility view;
    installation and documentation use the explicit package fields.
    """
    if not isinstance(value, Mapping):
        raise ValueError("Package definition must be an object")
    spec = copy.deepcopy(dict(value))
    digest(spec)  # Reject non-JSON objects and non-finite numbers before publication.
    if type(spec.get("schema_version")) is not int or spec["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported resource package schema")
    _identifier(spec.get("id"), "package id")
    if "version" not in spec:
        raise ValueError("version must be present; use null when it is unresolved")
    _string(spec.get("version"), "version", nullable=True)
    _string(spec.get("build"), "build")
    if spec.get("provider") not in PROVIDERS:
        raise ValueError("Unknown package provider")
    target = spec.get("target")
    if not isinstance(target, dict):
        raise ValueError("target must be an object")
    for key in DEFAULT_TARGET:
        _string(target.get(key), "target." + key)
    dependencies = spec.get("dependencies")
    if not isinstance(dependencies, dict) or set(dependencies) != {"build", "run", "system"}:
        raise ValueError("dependencies must define build, run and system lists")
    for phase, names in dependencies.items():
        _strings(names, "dependencies." + phase)
        if len(set(names)) != len(names):
            raise ValueError("Duplicate package dependency")
        for name in names:
            _identifier(name, "dependency id")
            if name == spec["id"] and phase != "system":
                raise ValueError("A package cannot depend on itself")
    sources = spec.get("sources")
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    source_ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Source definitions must be objects")
        _identifier(source.get("id"), "source id")
        if source["id"] in source_ids:
            raise ValueError("Duplicate source id")
        source_ids.add(source["id"])
        if not {"url", "sha256", "bytes", "material_path"}.issubset(source):
            raise ValueError("Source locks must contain explicit fields, using null for unknown values")
        _string(source.get("url"), "source.url", nullable=True)
        if source.get("sha256") is not None and (not isinstance(source["sha256"], str)
                                                 or not SHA256.fullmatch(source["sha256"])):
            raise ValueError("Invalid source SHA-256")
        if source.get("bytes") is not None and (type(source["bytes"]) is not int or source["bytes"] < 0):
            raise ValueError("Source bytes must be a nonnegative integer or null")
        _relative(source.get("material_path"), "source.material_path", nullable=True)
        for key in ("extract", "strip_root"):
            if type(source.get(key)) is not bool:
                raise ValueError("Source " + key + " must be boolean")
        if "bundled_path" in source:
            _relative(source["bundled_path"], "source.bundled_path")
    recipe = spec.get("recipe")
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be an object")
    if "wrapper" in recipe and type(recipe["wrapper"]) is not bool:
        raise ValueError("recipe.wrapper must be boolean")
    if recipe.get("wrapper"):
        _string(recipe.get("manager"), "recipe.manager")
        _string(recipe.get("package_name"), "recipe.package_name")
        phases = ["install_commands", "uninstall_commands"]
        if "install_from_cache_commands" in recipe:
            phases.append("install_from_cache_commands")
        for phase in phases:
            if not isinstance(recipe.get(phase), list) or not recipe[phase]:
                raise ValueError("Manager wrappers require explicit " + phase)
            for argv in recipe[phase]:
                _command(argv, "recipe." + phase)
    checks = spec.get("checks")
    if not isinstance(checks, list):
        raise ValueError("checks must be a list")
    check_ids = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Check definitions must be objects")
        _identifier(check.get("id"), "check id")
        if check["id"] in check_ids:
            raise ValueError("Duplicate check id")
        check_ids.add(check["id"])
        if check.get("kind") not in {"version", "availability", "functional", "hardware"}:
            raise ValueError("Unknown check kind")
        _command(check.get("argv"), "check.argv")
        _string(check.get("cwd"), "check.cwd")
        timeout = check.get("timeout_seconds")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Check timeout must be positive and finite")
        if type(check.get("expected_returncode")) is not int:
            raise ValueError("Check expected_returncode must be an integer")
        if "stdout_regex" in check:
            _string(check["stdout_regex"], "check.stdout_regex")
            try:
                re.compile(check["stdout_regex"])
            except re.error as error:
                raise ValueError("Invalid check stdout_regex") from error
        for key in ("requires_commands", "requires_paths"):
            if key in check:
                _strings(check[key], "check." + key)
        blocked = check.get("blocked_returncodes", [])
        if (not isinstance(blocked, list) or any(type(code) is not int for code in blocked)
                or len(set(blocked)) != len(blocked)
                or (blocked and check["kind"] != "hardware")
                or check["expected_returncode"] in blocked):
            raise ValueError("Only hardware checks may declare distinct blocked_returncodes")
    usage = spec.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("usage must be an object")
    _string(usage.get("summary"), "usage.summary")
    for key in ("activation", "notes", "documentation"):
        _strings(usage.get(key), "usage." + key)
    for key, fields in (("locations", ("label", "path", "purpose")),
                        ("examples", ("description", "command"))):
        if not isinstance(usage.get(key), list):
            raise ValueError("usage." + key + " must be a list")
        for row in usage[key]:
            if not isinstance(row, dict):
                raise ValueError("usage." + key + " entries must be objects")
            for field in fields:
                _string(row.get(field), "usage." + key + "." + field)
    metadata = spec.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    record = metadata.get("catalog")
    if record is not None:
        if not isinstance(record, dict):
            raise ValueError("metadata.catalog must be an object")
        if record.get("id") != spec["id"] or record.get("version") != spec["version"]:
            raise ValueError("Package id/version differs from its catalog view")
        if metadata.get("catalog_sha256") != digest(record):
            raise ValueError("Original catalog record identity differs")
        expected = _sources(record)
        if sources != expected:
            raise ValueError("Package source locks differ from its catalog view")
    return spec


def _sources(row):
    if row.get("kind") in {"group", "virtual", "host", "oci"}:
        return []
    source = {"id": row["id"], "url": row.get("source_url"), "sha256": row.get("sha256"),
              "bytes": row.get("archive_bytes"), "material_path": row.get("material_path"),
              "extract": bool(row.get("extract", False)), "strip_root": bool(row.get("strip_archive_root", True))}
    if row.get("bundled_path"):
        source["bundled_path"] = row["bundled_path"]
    return [source]


def _provider(row):
    kind, recipe = row.get("kind"), row.get("deployment", {})
    adapter = recipe.get("adapter")
    if kind == "apt":
        return "apt"
    if kind == "wheel":
        return "python"
    if adapter == "component":
        return "component"
    if kind == "host":
        return "host"
    if kind in {"group", "virtual", "oci"}:
        return "meta"
    if kind in {"native_bundle", "vendor-local"}:
        return "binary"
    if adapter in {"cmake", "make", "commands"} or recipe.get("handled_by") == "core-build-scripts":
        return "source"
    return "material"


def _checks(row):
    recipe = row.get("deployment", {})
    commands = ([recipe["smoke_argv"]] if recipe.get("smoke_argv") else [])
    commands += recipe.get("additional_smoke_commands", [])
    checks = []
    for index, argv in enumerate(commands, 1):
        kind = classify_legacy_check(argv, requires_host=bool(recipe.get("probe_requires_host")))
        checks.append({"id": f"declared-{index:03d}", "kind": kind, "argv": copy.deepcopy(argv),
                       "cwd": recipe.get("smoke_cwd", recipe.get("working_directory", "{prefix}")),
                       "timeout_seconds": 120, "expected_returncode": 0})
    return checks


def from_catalog_record(row: Mapping[str, Any], target=None) -> dict[str, Any]:
    """Translate one resource without dropping unknown fields or claiming success."""
    row = copy.deepcopy(dict(row))
    recipe = copy.deepcopy(row.get("deployment", {}))
    provider = _provider(row)
    if provider in {"apt", "python"}:
        # Wrapper packages describe how to call an existing package manager.
        # Their source locks identify its upstream packages, not an embedded
        # payload. Dependency resolution remains that manager's responsibility.
        recipe["wrapper"] = True
        recipe.setdefault("manager", "apt" if provider == "apt" else "pip")
        recipe.setdefault("package_name", row.get("package_name", row["id"]))
        commands = {
            "apt": (["apt-get", "install", "--yes", "--no-install-recommends", "{package_name}={version}"],
                    ["apt-get", "remove", "--yes", "{package_name}"]),
            "pip": (["{prefix}/bin/python", "-m", "pip", "install", "{package_name}=={version}"],
                    ["{prefix}/bin/python", "-m", "pip", "uninstall", "--yes", "{package_name}"]),
            "conda": (["conda", "install", "--yes", "--prefix", "{prefix}", "{package_name}={version}"],
                      ["conda", "remove", "--yes", "--prefix", "{prefix}", "{package_name}"]),
        }
        if recipe["manager"] in commands:
            install, uninstall = commands[recipe["manager"]]
            recipe.setdefault("install_commands", [install])
            recipe.setdefault("uninstall_commands", [uninstall])
        cached_commands = {
            "apt": ["apt-get", "install", "--yes", "--no-install-recommends", "{source}"],
            "pip": ["{prefix}/bin/python", "-m", "pip", "install", "{source}"],
        }
        if recipe["manager"] in cached_commands:
            recipe.setdefault("install_from_cache_commands", [cached_commands[recipe["manager"]]])
    dependencies = list(dict.fromkeys(row.get("dependencies", [])))
    system = sorted({name for name in dependencies if name.startswith("apt.")} |
                    set(row.get("apt_dependency_ids", [])))
    other = [name for name in dependencies if name not in system]
    checks = copy.deepcopy(row["checks"]) if "checks" in row else _checks(row)
    locations = []
    if row.get("material_path"):
        locations.append({"label": "Prepared material", "path": "{assets}/" + row["material_path"],
                          "purpose": "Independent verified source, input, data or upstream distribution."})
    if provider in {"source", "binary"}:
        locations.append({"label": "Installation prefix", "path": "{prefix}",
                          "purpose": "The selected version's independently installed files."})
    elif provider == "apt":
        locations.append({"label": "System package files", "path": "/var/lib/dpkg/info/" + row.get("package_name", row["id"]) + ".list",
                          "purpose": "Ask dpkg-query -L for the actual installed file list, including multiarch packages."})
    elif provider == "python":
        locations.append({"label": "Python environment", "path": "{prefix}",
                          "purpose": "Use this environment's interpreter to avoid mixing incompatible Python packages."})
    documents = row.get("documentation") or []
    if isinstance(documents, str):
        documents = [documents]
    notes = ["Definition migration records availability contracts, not successful acquisition, installation or execution."]
    if not checks and provider not in {"meta", "component", "material"}:
        notes.append("No executable usability check was declared by the original recipe; installation alone does not establish usability.")
    if recipe.get("adapter") in {"reference", "manual", "unresolved", "vendor-local"}:
        notes.append("The recorded installation recipe is not an automatically qualified installer; review the explicit preparation blockers.")
    if recipe.get("probe_requires_host"):
        notes.append("Some capabilities require host conditions: " + "; ".join(recipe["probe_requires_host"]) + ".")
    if row.get("kind") == "oci":
        notes.append("The environment creator manages this OCI image; it is not a separately installed resource payload.")
    if recipe.get("target_smoke_commands"):
        notes.append("Target-specific checks are retained in recipe.target_smoke_commands and must run in the declared target context.")
    examples = [{"description": "Run the recorded " + check["kind"] + " check.",
                 "command": shlex.join(check["argv"])} for check in checks]
    activation = []
    if provider == "apt":
        examples.append({"description": "List the files registered by the system package manager.",
                         "command": "dpkg-query -L {package_name}"})
    if provider == "python":
        activation.append("# No shell activation is required; invoke the selected environment's interpreter explicitly.")
        examples.append({"description": "Inspect package metadata in the selected environment.",
                         "command": ("conda list --prefix {prefix} --full-name {package_name}"
                                     if recipe.get("manager") == "conda" else
                                     "{prefix}/bin/python -m pip show {package_name}")})
    if recipe.get("wrapper"):
        notes.append("A payload-free wrapper forwards installation and removal to " + recipe["manager"] +
                     "; that manager resolves dependencies. Declared source locks identify upstream packages, not files bundled in this wrapper.")
    spec = {"schema_version": SCHEMA_VERSION, "id": row["id"], "version": row.get("version"),
            "build": "1", "target": copy.deepcopy(DEFAULT_TARGET if target is None else target),
            "provider": provider, "dependencies": {"build": other if provider == "source" else [],
                "run": other, "system": system}, "sources": _sources(row), "recipe": recipe,
            "checks": checks, "usage": {"summary": row.get("purpose") or row.get("title") or row["id"],
                "locations": locations, "activation": activation, "examples": examples,
                "notes": notes, "documentation": documents},
            "metadata": {"catalog": row, "catalog_sha256": digest(row)}}
    if "usage" in row:
        spec["usage"] = copy.deepcopy(row["usage"])
    return validate_spec(spec)


def preparation_blockers(value: Mapping[str, Any]) -> list[str]:
    """Return unresolved inputs without conflating a definition with deployment."""
    spec = validate_spec(value)
    blockers = []
    if spec["version"] is None:
        blockers.append("The resource version is unresolved.")
    for source in spec["sources"]:
        if source["sha256"] is None or source["bytes"] is None:
            blockers.append("Exact source SHA-256 and byte count are required: " + source["id"])
        if not source["url"] and not source.get("bundled_path"):
            blockers.append("A resolved source URL or explicitly supplied local payload is required: " + source["id"])
        if source["material_path"] is None:
            blockers.append("A material destination is unresolved: " + source["id"])
    recipe = spec["recipe"]
    if spec["provider"] in {"source", "binary"} and recipe.get("adapter") in {"reference", "manual", "unresolved", "vendor-local"}:
        blockers.append("The executable installation recipe is unresolved or requires an explicit local installer.")
    if recipe.get("submodule_closure_complete") is False or recipe.get("lfs_closure_complete") is False:
        blockers.append("The complete source/submodule/LFS closure is unavailable.")
    return blockers


def spec_for_selection(row: dict, registry) -> dict:
    """Preserve authored checks/usage when selection only adds admission facts.

    An explicit local import can confirm an existing exact source identity.
    Previously unresolved inputs or substantive recipe/source changes need a
    normalized definition of their own; they do not inherit qualification.
    """
    try:
        spec = registry.get(row["id"])
    except KeyError:
        spec = None
    if spec is not None:
        original = spec.get("metadata", {}).get("catalog")
        ignored = {"selection_required", "admission_status"}
        if row.get("local_payload"):
            admission = row["local_payload"]
            if (isinstance(original, dict) and isinstance(admission, dict)
                    and original.get("sha256") is not None and original.get("archive_bytes") is not None
                    and row.get("sha256") == original["sha256"] == admission.get("sha256")
                    and row.get("archive_bytes") == original["archive_bytes"] == admission.get("bytes")):
                ignored.update({"local_payload", "size_basis"})
        if (isinstance(original, dict) and {key: value for key, value in original.items() if key not in ignored}
                == {key: value for key, value in row.items() if key not in ignored}):
            return copy.deepcopy(spec)
    return from_catalog_record(row)
