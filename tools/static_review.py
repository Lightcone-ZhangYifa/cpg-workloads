"""Static admission of previously delivered CPG packages; never execute them."""
from __future__ import annotations

import ast
from pathlib import Path
import re
from urllib.parse import urlparse

POLICY = "static-trust-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE = re.compile(r"\{(recipe|tools)\}(/[^{}\s\"']*)?")
_FIELDS = ("schema_version", "id", "version", "build", "provider", "target",
           "dependencies", "sources", "recipe", "checks", "usage", "metadata")


def common_qualification_errors(record, manifest):
    """Identity, structure and license gates shared with execution-based admission."""
    errors = []
    spec = manifest.get("package")
    if not isinstance(spec, dict):
        return ["Package definition must be an object"]
    missing = [key for key in _FIELDS if key not in spec]
    if missing:
        return ["Missing package fields: " + ", ".join(missing)]
    for key in ("id", "version", "build", "target"):
        if record.get(key) != spec[key]:
            errors.append("Artifact identity differs from its template: " + key)
    if (record.get("method") != manifest.get("method")
            or record.get("manifest_sha256") != manifest.get("manifest_sha256")):
        errors.append("Artifact manifest identity differs")
    checksum = record.get("sha256")
    if (not isinstance(checksum, str) or not _SHA256.fullmatch(checksum)
            or type(record.get("bytes")) is not int or record["bytes"] <= 0):
        errors.append("Artifact byte identity is incomplete")
    if record.get("structure") != "passed":
        errors.append("The delivered archive must pass structural verification")
    metadata = spec.get("metadata")
    catalog = metadata.get("catalog", {}) if isinstance(metadata, dict) else {}
    if not isinstance(catalog, dict):
        catalog = {}
    if any(not catalog.get(key) for key in ("license_class", "license_id")):
        errors.append("License metadata is incomplete")
    if catalog.get("license_class") != "open" or catalog.get("redistributable") is False:
        errors.append("Public redistribution is not established by the original license metadata")
    return errors


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _commit_pinned_sources(spec):
    sources = spec.get("sources")
    if not isinstance(sources, list) or not sources:
        return False
    for source in sources:
        if not isinstance(source, dict):
            return False
        parsed = urlparse(source.get("url") or "")
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
                or not re.search(r"(?:^|/)[0-9a-f]{40}(?=$|[/.])", parsed.path)):
            return False
    return True


def _inventory_is_locked(manifest):
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        return False
    files = [row for row in rows if isinstance(row, dict) and row.get("kind") == "file"]
    return bool(files) and all(isinstance(row.get("sha256"), str)
                               and _SHA256.fullmatch(row["sha256"])
                               and type(row.get("bytes")) is int and row["bytes"] >= 0
                               for row in files)


def static_review(record, manifest, template):
    """Return reproducible review results without changing historical runtime evidence.

    The caller first verifies the complete archive with CPG's existing verifier.
    This function checks metadata and authored recipe/check files in its unpacked
    template. A passing result says nothing about newly executed build or tests.
    """
    # Imported at call time so import_archives can use this module's common gate.
    from import_archives import safe_relative, source_locks_complete

    errors = common_qualification_errors(record, manifest)
    warnings = []
    checks = {"runtime_execution": "not_performed", "python_files_parsed": 0,
              "referenced_template_paths": []}
    spec = manifest.get("package", {})
    if not isinstance(spec, dict) or any(key not in spec for key in _FIELDS):
        return {"policy": POLICY, "status": "failed", "errors": errors,
                "warnings": warnings, "checks": checks}
    method, recipe = manifest.get("method"), spec.get("recipe")
    template = Path(template)
    root = template.resolve()
    if not isinstance(spec.get("provider"), str) or not spec["provider"]:
        errors.append("Provider is missing")
    target = spec.get("target")
    if not isinstance(target, dict) or any(not target.get(key) for key in ("os", "arch")):
        errors.append("Target OS and architecture are required")
    dependencies = spec.get("dependencies")
    if (not isinstance(dependencies, dict) or set(dependencies) != {"build", "run", "system"}
            or any(not isinstance(items, list) for items in dependencies.values())):
        errors.append("Dependencies must declare build, run and system lists")
    if not isinstance(recipe, dict) or not any(recipe.get(key) for key in ("adapter", "manager")):
        errors.append("A recipe adapter or package-manager entry is required")
        recipe = {} if not isinstance(recipe, dict) else recipe
    if recipe.get("adapter") == "commands" and not recipe.get("commands"):
        errors.append("The commands recipe has no build/preparation command")
    try:
        locked = source_locks_complete(manifest)
    except (KeyError, TypeError, AttributeError):
        locked = False
    if locked:
        checks["source_locks"] = "complete"
    elif method == "binary" and _commit_pinned_sources(spec) and _inventory_is_locked(manifest):
        checks["source_locks"] = "commit_pinned_with_locked_delivered_inventory"
        warnings.append("Delivered binary has complete payload hashes and commit-pinned HTTPS sources, "
                        "but its historical definition omits source archive byte locks. Source rebuilding "
                        "is not newly established by this static review.")
    else:
        errors.append("Effective source locks are incomplete or changed fixed fields")
    declarations = spec.get("checks")
    if not isinstance(declarations, list) or any(not isinstance(row, dict) for row in declarations):
        errors.append("Checks must be a list of declarations")
        declarations = []
    apt = method == "wrapper" and spec.get("provider") == "apt" and recipe.get("manager") == "apt"
    # Historical catalogs sometimes label executable binary packages as provider
    # "material". The shipped artifact method determines the check requirement.
    material = method == "material"
    required_kinds = {"functional", "availability", "integrity"} if material else {"functional"}
    admitted = [row for row in declarations if row.get("kind") in required_kinds]
    checks["check_declarations"] = "apt_exempt" if apt else ("material_read_or_integrity" if material else "functional")
    if not apt and not admitted:
        errors.append("A material package needs a read/integrity check declaration" if material else
                      "A non-APT software package needs a functional check declaration")
    identifiers = [row.get("id") for row in declarations]
    if any(not isinstance(item, str) or not item for item in identifiers) or len(set(identifiers)) != len(identifiers):
        errors.append("Check declarations need unique nonempty IDs")
    for row in declarations:
        argv = row.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
            errors.append("A check declaration has no executable argv: " + str(row.get("id")))
        elif (row.get("kind") == "functional" and len(argv) == 2
              and argv[1] in {"--version", "-V", "--help", "-h"}):
            errors.append("A version/help-only command is not a functional check: " + row["id"])
    references = set()
    for text in _strings([recipe, declarations]):
        for match in _REFERENCE.finditer(text):
            references.add(match.group(1) + (match.group(2) or ""))
    for relative in sorted(references):
        try:
            path = template / safe_relative(relative)
            if not path.resolve().is_relative_to(root) or not path.exists():
                raise ValueError("Missing or escaping template reference: " + relative)
            checks["referenced_template_paths"].append(relative)
        except (OSError, ValueError) as error:
            errors.append(str(error))
    for directory in (template / "recipe", template / "tools"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            try:
                if not path.resolve().is_relative_to(root):
                    raise ValueError("Python template file escapes its source directory")
                ast.parse(path.read_bytes(), filename=str(path.relative_to(template)))
                checks["python_files_parsed"] += 1
            except (OSError, SyntaxError, ValueError) as error:
                errors.append(str(path.relative_to(template)) + ": " + str(error))
    return {"policy": POLICY, "status": "passed" if not errors else "failed",
            "errors": errors, "warnings": warnings, "checks": checks}
