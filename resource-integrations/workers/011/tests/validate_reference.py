#!/usr/bin/env python3
"""Exercise real offline retrieval and reject damaged reference material copies."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root: Path) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    snapshot = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob("*") if p.is_file()}
    inventory_sha = snapshot["inventory.json"]
    network_attempts = []
    subprocess_attempts = []

    def audit(event, args):
        if event.startswith("socket."):
            network_attempts.append(event)
            raise RuntimeError("network is forbidden during reference validation")
        if event in ("subprocess.Popen", "os.system", "os.posix_spawn"):
            subprocess_attempts.append(event)
            raise RuntimeError("subprocess is forbidden during reference validation")

    sys.addaudithook(audit)
    spec = importlib.util.spec_from_file_location("worker011_reference", root / "reference_library.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = []

    def record(name: str, details):
        checks.append({"name": name, "status": "passed", "details": details})

    lib = module.ReferenceLibrary(root, expected_inventory_sha256=inventory_sha)
    verified = lib.verify()
    assert verified["assets"] == 4 and verified["upstream_files"] == 60
    assert verified["tool_functional"] is None and verified["dataset_verified"] is None
    record("complete_fixed_material_inventory", verified)

    query_cases = [
        ("reference.doc.openmp-opt", "globalization"),
        ("reference.doc.openmp-opt", "-Rpass=openmp-opt"),
        ("reference.doc.llvm-remarks", "Hotness"),
        ("reference.doc.llvm-remarks", "LLVMRemarkParserCreateYAML"),
        ("reference.doc.llvm-testsuite", "TEST_SUITE_BENCHMARKING_ONLY"),
        ("reference.doc.mlir-sparse", "sparse_tensor.convert"),
        ("reference.doc.mlir-sparse", "has_runtime_library"),
    ]
    for asset, query in query_cases:
        hits = lib.search(query, asset_id=asset, limit=8)
        assert hits, (asset, query)
        for hit in hits:
            assert asset in hit["asset_ids"]
            original = lib.read(hit["upstream_path"], line=hit["line"], count=1)
            assert original["lines"][0]["text"] == hit["text"]
            assert original["source_sha256"] == hit["source_sha256"]
        record("query_" + asset + "_" + query, {"query": query, "hits": len(hits), "first_locator": hits[0]})

    sparse = [r for r in lib.chapters("reference.doc.mlir-sparse") if r["kind"] == "sparse_tensor_operation"]
    assert len(sparse) == 37 and len({r["title"] for r in sparse}) == 37
    for row in sparse:
        excerpt = lib.read(row["upstream_path"], line=row["line"], count=min(500, row["end_line"] - row["line"] + 1))
        text = "\n".join(x["text"] for x in excerpt["lines"])
        assert row["tablegen_definition"] in text and '"' + row["title"].split(".", 1)[1] + '"' in text
    record("all_37_sparse_operation_locators_resolve", {"operations": len(sparse)})

    for asset in module.ASSET_IDS:
        assert lib.chapters(asset)
    record("all_four_assets_have_chapter_or_symbol_index", {"assets": list(module.ASSET_IDS)})

    for args in [lambda: lib.search("", limit=1), lambda: lib.search("x", limit=0),
                 lambda: lib.search("x", asset_id="unknown"), lambda: lib.read("../LICENSE"),
                 lambda: lib.read("llvm/docs/Remarks.rst", line=0)]:
        try:
            args()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid query/read accepted")
    record("invalid_input_boundaries", {"rejections": 5})

    source = "materials/upstream/llvm/docs/Remarks.rst"
    def reject(name, mutate, expected=True):
        with tempfile.TemporaryDirectory(prefix="worker011-negative-", dir=root.parent) as tmp:
            target = Path(tmp) / "reference"
            shutil.copytree(root, target, copy_function=shutil.copyfile)
            candidate = mutate(target)
            candidate = candidate if isinstance(candidate, Path) else target
            try:
                module.ReferenceLibrary(candidate, expected_inventory_sha256=inventory_sha if expected else None)
            except (module.IntegrityError, ValueError, OSError) as e:
                record(name, {"rejected": True, "error": str(e)})
            else:
                raise AssertionError("tampered copy accepted: " + name)

    reject("changed_source_rejected", lambda d: (d / source).write_bytes((d / source).read_bytes() + b"changed"))
    reject("missing_source_rejected", lambda d: (d / source).unlink())
    reject("unexpected_source_rejected", lambda d: (d / "materials/upstream/extra.rst").write_text("unexpected"))
    reject("changed_index_rejected", lambda d: (d / "indexes/entries.jsonl").write_text("{}\n"))
    reject("changed_inventory_rejected_by_external_hash", lambda d: (d / "inventory.json").write_text((d / "inventory.json").read_text() + " "))

    def symlink_file(d):
        (d / source).unlink()
        (d / source).symlink_to(root / source)
    reject("symlink_source_rejected", symlink_file)

    def hardlink_file(d):
        (d / source).unlink()
        os.link(root / source, d / source)
    reject("hardlink_source_rejected", hardlink_file)

    def symlink_dir(d):
        shutil.rmtree(d / "indexes")
        (d / "indexes").symlink_to(root / "indexes", target_is_directory=True)
    reject("symlink_directory_rejected", symlink_dir)

    def root_symlink(d):
        alias = d.parent / "alias"
        alias.symlink_to(d, target_is_directory=True)
        return alias
    reject("symlink_root_rejected", root_symlink)
    reject("nested_manager_filename_not_exempt", lambda d: (d / "indexes/.cpg-prefix.json").write_text("{}"))

    def state_symlink(d):
        (d / ".cpg-prefix.json").symlink_to(root / "assets.json")
    reject("manager_state_symlink_rejected", state_symlink)

    with tempfile.TemporaryDirectory(prefix="worker011-manager-", dir=root.parent) as tmp:
        target = Path(tmp) / "reference"
        shutil.copytree(root, target, copy_function=shutil.copyfile)
        (target / ".cpg-prefix.json").write_text('{"owner":"CPG"}\n')
        module.ReferenceLibrary(target, expected_inventory_sha256=inventory_sha).verify()
        record("ordinary_manager_ownership_file_supported", {"file": ".cpg-prefix.json"})

    after = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob("*") if p.is_file()}
    assert after == snapshot
    assert network_attempts == [] and subprocess_attempts == []
    record("source_bundle_unchanged", {"files": len(snapshot), "inventory_sha256": inventory_sha})
    record("offline_consumption_observed", {"network_attempts": 0, "subprocess_attempts": 0,
                                           "mechanism": "Python audit hook; not an OS network namespace proof"})
    return {"schema_version": 1, "worker_id": "worker 011", "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(), "status": "passed",
            "python": platform.python_version(), "platform": " ".join(os.uname()),
            "inventory_sha256": inventory_sha, "checks_passed": len(checks), "checks": checks,
            "qualification": {"reference_assets_verified": 4, "tool_functional": None,
                              "official_benchmark": None, "dataset_verified": None}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root.absolute())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, ensure_ascii=False, indent=2))
