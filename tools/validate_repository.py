#!/usr/bin/env python3
"""Validate software-source layout, immutable identities, and publication gates."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

from import_archives import safe_relative
from release import (ROOT, artifact_name, digest, load_json, load_manifest, publication_errors,
                     published_rows, published_recipes, row_asset_name, sha256,
                     verify_binary, verify_evidence, verify_material)


def validate(root=ROOT):
    errors = []
    definitions = {}
    for path in sorted((root / "packages").glob("*/package.json")):
        try:
            spec = json.loads(path.read_text())
            if spec["id"] != path.parent.name:
                raise ValueError("Package directory differs from its ID")
            for key in ("schema_version", "id", "version", "build", "provider", "target", "dependencies",
                        "sources", "recipe", "checks", "usage", "metadata"):
                if key not in spec:
                    raise ValueError("Missing package field " + key)
            if set(spec["dependencies"]) != {"build", "run", "system"}:
                raise ValueError("Invalid dependency phases")
            definitions[spec["id"]] = spec
        except (ValueError, KeyError, TypeError) as error:
            errors.append(f"{path.relative_to(root)}: {error}")
    registry_path = root / "packages/registry.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text())
        order = registry.get("resource_order", [])
        if len(order) != len(set(order)) or set(order) != set(definitions):
            errors.append("Registry order must name every current definition exactly once")
    else:
        errors.append("packages/registry.json is missing")
    for identifier, spec in definitions.items():
        for dependencies in spec["dependencies"].values():
            if set(dependencies) - set(definitions):
                errors.append(identifier + ": missing declared dependency")
    records = {}
    for path in sorted((root / "catalog/artifacts").glob("*.json")):
        try:
            row = load_json(path)
            if row["sha256"] != path.stem or not re.fullmatch(r"[0-9a-f]{64}", path.stem):
                raise ValueError("Artifact record path differs from checksum")
            template = root / safe_relative(row["template"])
            if not template.is_dir() or template.is_symlink():
                raise ValueError("Template directory is missing or a symlink")
            if row["method"] != "online-recipe":
                manifest = load_manifest(template)
                spec = manifest["package"]
                for field in ("id", "version", "build", "target"):
                    if row[field] != spec[field]:
                        raise ValueError("Artifact and template identity differ: " + field)
                if row["manifest_sha256"] != manifest["manifest_sha256"] or row["method"] != manifest["method"]:
                    raise ValueError("Artifact and manifest identity differ")
                if row["asset_name"] != artifact_name(spec, row["method"], row["sha256"]):
                    raise ValueError("Noncanonical release filename")
                for member in manifest["files"]:
                    relative = safe_relative(member["path"])
                    if relative.parts[0] not in {"recipe", "tools"}:
                        continue
                    source = template / relative
                    if member["kind"] == "file":
                        if (source.is_symlink() or not source.is_file() or source.stat().st_size != member["bytes"]
                                or sha256(source) != member["sha256"]):
                            raise ValueError("Authored template member identity mismatch: " + member["path"])
                if row["release_eligible"]:
                    problems = publication_errors(row, manifest)
                    if problems:
                        raise ValueError("; ".join(problems))
                    verify_evidence(row, template)
                    if row["method"] == "material" and row.get("review_policy") != "static-trust-v1":
                        verify_material(row, manifest, template)
                    elif row["method"] == "binary" and row.get("review_policy") != "static-trust-v1":
                        verify_binary(row, manifest, template)
            else:
                from online_recipe import verify_template
                verify_template(template, row)
                if row.get("asset_name") != row_asset_name(row):
                    raise ValueError("Noncanonical online recipe filename")
                if row["release_eligible"] and (row.get("review_policy") != "static-trust-v1"
                        or row.get("static_review", {}).get("status") != "passed"):
                    raise ValueError("Online recipe lacks an explicit static review")
            records[row["sha256"]] = row
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(f"{path.relative_to(root)}: {error}")
    planned_identities = {}
    for path in sorted((root / "release-plans").glob("*.json")):
        try:
            plan = json.loads(path.read_text())
            if plan["tag"] != path.stem or not 1 <= len(plan["artifacts"]) <= 950:
                raise ValueError("Invalid release plan identity or size")
            if len(plan["artifacts"]) != len(set(plan["artifacts"])):
                raise ValueError("Duplicate artifact in release plan")
            for checksum in plan["artifacts"]:
                if checksum not in records or not records[checksum]["release_eligible"]:
                    raise ValueError("Plan references an absent or unqualified artifact")
                row = records[checksum]
                key = digest({name: row[name] for name in ("id", "version", "build", "method", "target")})
                if key in planned_identities and planned_identities[key] != checksum:
                    raise ValueError("Different release plans assign different bytes to one immutable package identity")
                planned_identities[key] = checksum
        except (ValueError, KeyError, TypeError) as error:
            errors.append(f"{path.relative_to(root)}: {error}")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("kind") != "compiler_playground_package_repository" or manifest.get("schema_version") != 1:
        errors.append("Unsupported root manifest")
    receipts = []
    for path in sorted((root / "catalog/releases").glob("*.json")):
        try:
            if path.is_symlink():
                raise ValueError("Publication receipts must be ordinary source files")
            receipts.append((path.stem, json.loads(path.read_text())))
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(f"{path.relative_to(root)}: {error}")
    try:
        verified, releases = published_rows(receipts)
    except (ValueError, KeyError, TypeError) as error:
        errors.append("Publication receipts: " + str(error))
        verified, releases = {}, []
    published = {row["sha256"]: row for row in verified.values()}
    expected = sorted(verified.values(), key=lambda row: (row["id"], row["version"], row["build"], row["method"], row["sha256"]))
    if manifest.get("packages", []) != expected:
        errors.append("Root manifest does not exactly preserve every verified publication")
    if manifest.get("releases", []) != releases:
        errors.append("Root manifest release summaries differ from verified receipts")
    if manifest.get("online_recipes", []) != published_recipes():
        errors.append("Root online recipes differ from verified publication receipts")
    identities = set()
    for row in manifest.get("packages", []):
        key = digest({name: row[name] for name in ("id", "version", "build", "method", "target")})
        if key in identities:
            errors.append("Duplicate package identity in root manifest")
        identities.add(key)
        if row["sha256"] not in published or published[row["sha256"]] != row:
            errors.append("Root manifest includes an unpublished or different artifact")
        if row["path"] != "packages/sha256/" + row["sha256"] + ".cpgpkg.tar.gz":
            errors.append("Non-content-addressed mirror path")
        url = urlparse(row.get("download_url", ""))
        if url.scheme != "https" or not url.netloc or url.username or url.password or url.fragment:
            errors.append("Unsafe release download URL")
    for path in root.rglob("*"):
        if any(part in {".git", "__pycache__", ".venv", "build", "dist"} for part in path.relative_to(root).parts):
            continue
        if path.is_file() and any(path.name.endswith(suffix) for suffix in (
                ".cpgpkg.tar.gz", ".cpgrecipe.tar.gz", ".whl", ".deb", ".o", ".so", ".a")):
            errors.append("Build or package output is inside the source tree: " + str(path.relative_to(root)))
    return {"status": "passed" if not errors else "failed", "definitions": len(definitions),
            "audited_artifacts": len(records), "published_packages": len(manifest.get("packages", [])),
            "errors": errors}


def main():
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
