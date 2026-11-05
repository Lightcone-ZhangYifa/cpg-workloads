#!/usr/bin/env python3
"""Prepare the original resource's explicitly declared complete MBPP subtree.

The canonical monorepo archive URL and unresolved archive identity remain
unchanged. This recipe acquires the exact three MBPP subtree blobs and original
root LICENSE already bound by the formal 0.21.11 Dataset source specification.
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
from compiler_playground.datasets.coding_tasks import coding_task_spec
from source_material import acquire_mbpp

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
    locks = json.loads((root / "recipe/source-subtree-locks.json").read_text())
    for key, value in locks["preserved_definition_fields"].items():
        actual = spec["metadata"]["catalog"] if key == "metadata.catalog" else spec[key]
        if actual != value:
            raise ValueError("Original canonical resource field changed: " + key)
    reviewed = coding_task_spec("mbpp")
    if reviewed != locks["formal_v02111_dataset_source_spec"]:
        raise ValueError("Installed CPG MBPP source specification differs from the exact frozen source identity")
    if locks["declared_subtree_scope"] not in spec["metadata"]["catalog"]["qualification_gaps"]:
        raise ValueError("The original resource contract does not explicitly permit this exact subtree scope")
    receipts = []
    for source in reviewed["source_materials"]["files"]:
        request = {"id": spec["id"] + ":" + source["path"], "source_url": source["url"],
                   "sha256": source["sha256"], "archive_bytes": source["bytes"],
                   "license_class": spec["metadata"]["catalog"]["license_class"]}
        if a.no_network:
            request["bundled_path"] = str(a.cache / "sha256" / source["sha256"][:2] / source["sha256"])
        receipt = {}
        acquire_file(request, a.cache, receipt=receipt)
        receipts.append(receipt)
    with tempfile.TemporaryDirectory(prefix="cpg-mbpp-declared-subtree-") as temporary:
        payload, acquired = acquire_mbpp(Path(temporary) / "material", blob_root=a.cache)
        expected = json.loads((root / "recipe/material-manifest.json").read_text())
        if inventory(payload) != expected["files"]:
            raise ValueError("Complete MBPP subtree material differs from the exact frozen identity")
        packed = pack(spec, a.output, method="material", payload=payload, recipe_dir=root / "recipe",
            provenance={"execution_category": "declared_mbpp_subtree_material_only",
                        "monorepo_not_acquired": True, "original_source_locks": spec["sources"],
                        "source_subtree_locks_sha256": hashlib.sha256((root / "recipe/source-subtree-locks.json").read_bytes()).hexdigest(),
                        "source_commit": reviewed["revision"],
                        "mbpp_subtree_git_sha1": reviewed["source_materials"]["subtree_git_tree_sha1"],
                        "native_execution_qualified": False, "dataset_qualification_increment": 0})
    verify_package(a.output, expected_sha256=packed["sha256"], expected_bytes=packed["bytes"])
    print(json.dumps({"status": "passed", "artifact": packed, "acquisitions": receipts,
        "source_commit": reviewed["revision"], "source_subtree": "mbpp", "original_files": 4,
        "monorepo_not_acquired": True, "programs_executed": False}, indent=2))

if __name__ == "__main__":
    main()
