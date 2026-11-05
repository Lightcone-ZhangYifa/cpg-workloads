"""Keep two reviewed XED build dependencies outside the authored source tree.

This exception is tied to one original artifact and manifest. It does not permit
arbitrary missing recipe files, change a CPG archive, or execute its build recipe.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


ARTIFACT = "ebfdbd07ae1bd20b4c5ec2f5caf376c9612501bdec481a9820138cd2dcbeefda"
MANIFEST = "478baa981de78ba5798cf8a19f656596972b30ae78255580499d3e2775c2bc9a"
DESCRIPTOR = "authored-inputs.json"
INPUTS = {
    "recipe/vendor/python3-pkg-resources_68.1.2-2ubuntu1.2_all.deb": {
        "sha256": "13caaa69d5ba8b02e90087d4bcef714c0581e591e820804d15d12f582055147a",
        "bytes": 167914,
    },
    "recipe/vendor/python3-setuptools_68.1.2-2ubuntu1.2_all.deb": {
        "sha256": "27ede03d8c5046c30cf1dcdc8835708408d27bdd3561e881b5d66656e6ff23e7",
        "bytes": 396614,
    },
}


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _ordinary(path, root):
    return (not path.is_symlink() and path.is_file()
            and path.resolve().is_relative_to(root.resolve()))


def descriptor_for(record, manifest, template):
    """Derive the only accepted mapping from immutable inventory and config."""
    if record.get("sha256") != ARTIFACT:
        return None
    if (record.get("id") != "uica.supplement.xed" or record.get("method") != "binary"
            or record.get("manifest_sha256") != MANIFEST
            or manifest.get("manifest_sha256") != MANIFEST
            or manifest.get("method") != "binary"
            or manifest.get("package", {}).get("id") != "uica.supplement.xed"):
        raise ValueError("External authored inputs belong to a different original package")
    template = Path(template)
    inventory = {row["path"]: row for row in manifest["files"]}
    if len(inventory) != len(manifest["files"]):
        raise ValueError("External authored inputs require a unique original inventory")
    config_path = template / "recipe/config.json"
    config_row = inventory.get("recipe/config.json", {})
    if (config_row.get("kind") != "file" or not _ordinary(config_path, template)
            or config_path.stat().st_size != config_row.get("bytes")
            or config_row.get("bytes", 0) > 128 * 1024
            or _sha(config_path) != config_row.get("sha256")):
        raise ValueError("Original recipe input configuration differs from its inventory")
    config = json.loads(config_path.read_text())
    entries = config.get("recipe_inputs")
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError("Original recipe configuration has no input list")
    by_path = {}
    for row in entries:
        name = "recipe/" + str(row.get("filename", ""))
        if name in INPUTS:
            if name in by_path:
                raise ValueError("Duplicate original authored input")
            by_path[name] = row
    if set(by_path) != set(INPUTS):
        raise ValueError("Original configuration omits a reviewed build input")
    members = {}
    for name, locked in INPUTS.items():
        source, row = by_path[name], inventory.get(name, {})
        expected_url = "https://archive.ubuntu.com/ubuntu/pool/main/s/setuptools/" + Path(name).name
        url = urlparse(source.get("url", ""))
        if (source.get("kind") != "precompiled_build_dependency"
                or source.get("url") != expected_url or url.query or url.fragment
                or url.username or url.password or source.get("extract") is not False
                or row.get("kind") != "file" or row.get("mode") != 0o444
                or any(row.get(key) != value or source.get(key) != value
                       for key, value in locked.items())):
            raise ValueError("Reviewed build input differs from its original inventory/source lock")
        members[name] = {"url": expected_url, **locked, "mode": row["mode"],
                         "kind": "precompiled_build_dependency", "id": source["id"]}
    return {"schema_version": 1, "kind": "cpg_external_authored_inputs",
            "artifact_sha256": ARTIFACT, "manifest_sha256": MANIFEST,
            "configuration": {"path": "recipe/config.json", "sha256": config_row["sha256"],
                              "bytes": config_row["bytes"]},
            "members": members}


def review_for(descriptor):
    return {"status": "passed", "source_type": "exact_original_recipe_inputs",
            "artifact_sha256": ARTIFACT, "manifest_sha256": MANIFEST,
            "descriptor_sha256": hashlib.sha256(_encoded(descriptor)).hexdigest(),
            "runtime_execution": "not_performed"}


def verify_authored_inputs(record, manifest, template):
    """Return locked external members; every other template file stays required."""
    template = Path(template)
    path = template / DESCRIPTOR
    review = record.get("authored_inputs_review")
    if review is None and not path.exists() and not path.is_symlink():
        return {}
    descriptor = descriptor_for(record, manifest, template)
    if descriptor is None or not _ordinary(path, template):
        raise ValueError("Unexpected or missing external authored-input descriptor")
    encoded = _encoded(descriptor)
    if (path.stat().st_size != len(encoded) or path.read_bytes() != encoded
            or review != review_for(descriptor)):
        raise ValueError("External authored-input descriptor/review differs from its original locks")
    for name in descriptor["members"]:
        target = template / name
        if target.exists() or target.is_symlink():
            raise ValueError("Finished build dependency must remain outside the source checkout: " + name)
    return descriptor["members"]


def externalize_authored_inputs(record, manifest, template):
    """After full original-package verification, retain locks and discard copies.

    This only touches the two exact dependency copies in the newly imported
    template. The original CPG archive and its manifest are never changed.
    """
    template = Path(template)
    descriptor = descriptor_for(record, manifest, template)
    if descriptor is None:
        return {}
    existing = []
    for name, locked in descriptor["members"].items():
        path = template / name
        if path.exists() or path.is_symlink():
            if (not _ordinary(path, template) or path.stat().st_size != locked["bytes"]
                    or _sha(path) != locked["sha256"]):
                raise ValueError("Imported build dependency differs from its original byte identity")
            existing.append(path)
    target = template / DESCRIPTOR
    data = _encoded(descriptor)
    if target.exists() or target.is_symlink():
        if not _ordinary(target, template) or target.read_bytes() != data:
            raise ValueError("Refusing to replace another authored-input descriptor")
    else:
        target.write_bytes(data)
    record["authored_inputs_review"] = review_for(descriptor)
    for path in existing:
        path.unlink()
    return verify_authored_inputs(record, manifest, template)
