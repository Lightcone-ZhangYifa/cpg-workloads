#!/usr/bin/env python3
"""Prepare complete historical CLgen source archive material with all original links.

No local model, learned generator or upstream program is installed or executed.
The existing CPG archive-set helper preserves all bytes and unresolved links.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from compiler_playground.resource_deploy import acquire_file
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.archive import inventory
from compiler_playground.packages.spec import validate_spec
from archive_set import assemble

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--definition", type=Path, default=Path(__file__).resolve().parents[1] / "package.json")
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--no-network", action="store_true")
    a = p.parse_args()
    a.cache = a.cache.resolve()
    root = a.definition.resolve().parent
    spec = validate_spec(json.loads(a.definition.read_text()))
    locks = json.loads((root / "recipe/acquisition-locks.json").read_text())
    for key, expected in locks["preserved_definition_fields"].items():
        actual = spec["metadata"]["catalog"] if key == "metadata.catalog" else spec[key]
        if actual != expected:
            raise ValueError("Original canonical resource identity changed: " + key)
    main_lock = locks["resolved_main_source"]
    for key, value in spec["sources"][0].items():
        if not (value is None and key in ("sha256", "bytes")) and main_lock[key] != value:
            raise ValueError("Supplemental main acquisition lock replaced a fixed source fact")
    receipts = []
    for lock in [main_lock] + locks["additional_acquisition_locks"]:
        request = {"id": lock["id"], "source_url": lock["url"], "sha256": lock["sha256"],
                   "archive_bytes": lock["bytes"], "license_class": spec["metadata"]["catalog"]["license_class"]}
        if a.no_network:
            request["bundled_path"] = str(a.cache / "sha256" / lock["sha256"][:2] / lock["sha256"])
        receipt = {}
        acquire_file(request, a.cache, receipt=receipt)
        receipts.append(receipt)
    raw = a.cache / "sha256" / main_lock["sha256"][:2] / main_lock["sha256"]
    with tempfile.TemporaryDirectory(prefix="cpg-clgen-original-archive-set-") as temporary:
        payload = Path(temporary) / "payload"
        result = assemble(raw, main_lock, locks["additional_acquisition_locks"], a.cache, payload)
        expected = json.loads((root / "recipe/material-manifest.json").read_text())
        if inventory(payload) != expected["files"]:
            raise ValueError("Complete original archive set differs from its frozen material identity")
        packed = pack(spec, a.output, method="material", payload=payload, recipe_dir=root / "recipe",
            provenance={"original_source_locks": spec["sources"],
                        "resolved_acquisition_locks": [main_lock] + locks["additional_acquisition_locks"],
                        "source_closure_audit_sha256": hashlib.sha256((root / "recipe/source-closure-audit.json").read_bytes()).hexdigest(),
                        "execution_category": "archive_set_preserved_upstream_broken_links",
                        "material_representation": "complete_original_archive_set_container",
                        "source_tree_deployment": False, "native_execution_qualified": False})
    verify_package(a.output, expected_sha256=packed["sha256"], expected_bytes=packed["bytes"])
    print(json.dumps({"status": "passed", "artifact": packed, "acquisitions": receipts,
        "original_regular_members": result["original_regular_members"],
        "original_link_members": result["original_link_members"], "source_tree_deployment": False}, indent=2))

if __name__ == "__main__":
    main()
