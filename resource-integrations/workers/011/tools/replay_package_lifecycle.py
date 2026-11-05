"""Replay a worker bundle with the existing CPG PackageManager.

This is a validation driver. It does not replace the CPG installer, mutate the
default resource catalog, or grant official Benchmark/OCI/hardware admission.
The output directory must not already exist. All failure evidence is retained.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import stat
import sys
import traceback

from compiler_playground.packages import PackageManager, Registry, verify_package


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def independent(first: Path, second: Path) -> dict:
    left = {p.relative_to(first): p for p in first.rglob("*")
            if p.is_file() and not p.is_symlink() and p.name != ".cpg-prefix.json"}
    right = {p.relative_to(second): p for p in second.rglob("*")
             if p.is_file() and not p.is_symlink() and p.name != ".cpg-prefix.json"}
    require(set(left) == set(right), "A/B installed file sets differ")
    for name, path in left.items():
        a, b = path.stat(), right[name].stat()
        require((a.st_dev, a.st_ino) != (b.st_dev, b.st_ino), "Shared A/B inode: " + str(name))
        require(a.st_nlink == b.st_nlink == 1, "Hard-linked installation: " + str(name))
        require(sha(path) == sha(right[name]), "A/B bytes differ: " + str(name))
    return {"status": "passed", "ordinary_files_compared": len(left), "shared_regular_inodes": 0}


def replay(bundle: Path, output: Path) -> dict:
    require(not output.exists() and not output.is_symlink(), "Use a fresh output directory")
    output.mkdir(parents=True)
    summary = {"schema_version": 1, "status": "running",
               "framework_version": importlib.metadata.version("compiler-playground"),
               "bundle": str(bundle), "qualification_scope": "explicit worker package profiles",
               "old_resource_increment": 0, "official_benchmark": None, "oci": None,
               "hardware": None, "packages": []}
    try:
        require(summary["framework_version"] == "0.21.14", "Replay requires the declared CPG 0.21.14 baseline")
        original = Registry.load()
        original_value = original.to_dict()
        extension = Registry.load(bundle / "cpg" / "registry.json")
        collisions = set(original) & set(extension)
        require(not collisions, "The extension shadows original IDs: " + repr(sorted(collisions)))
        index = json.loads((bundle / "cpg" / "package-index.json").read_text())
        require(set(index["package_ids"]) == set(extension), "Package index and extension registry differ")
        managers = {
            side: PackageManager(state=output / side / "state", prefix_root=output / side / "prefixes",
                                 cache=output / "raw-cache", registry=extension)
            for side in ("a", "b")
        }
        for item in index["artifacts"]:
            archive = bundle / item["path"]
            checked = verify_package(archive, expected_sha256=item["sha256"], expected_bytes=item["bytes"])
            name = item["id"]
            require(checked["manifest"]["package"] == extension.get(name), "Artifact definition differs from registry")
            entry = {"id": name, "method": checked["manifest"]["method"],
                     "artifact_sha256": item["sha256"], "installs": {}}
            summary["packages"].append(entry)
            records = {}
            prefixes = {side: output / side / "prefixes" / name for side in managers}
            for side, manager in managers.items():
                record = manager.install(archive, prefix=prefixes[side], check=True)
                records[side] = record
                require(record["installation"]["status"] == "installed", "Installation failed")
                require(record["checks"]["status"] == "passed", "Declared checks failed")
                require(manager.verify_installed(name, prefix=prefixes[side])["status"] == "verified", "Installed inventory mismatch")
                entry["installs"][side] = {"status": record["status"], "checks": record["checks"],
                                           "compatibility": record["compatibility"],
                                           "installed_inventory_sha256": record["installed_inventory_sha256"]}
            entry["independence"] = independent(prefixes["a"], prefixes["b"])
            chosen = next(p for p in prefixes["a"].rglob("*")
                          if p.is_file() and not p.is_symlink() and p.name != ".cpg-prefix.json")
            before = chosen.read_bytes()
            try:
                chosen.write_bytes(before + b"\nCPG_TAMPER_NEGATIVE_CONTROL\n")
                require(managers["a"].verify_installed(name, prefix=prefixes["a"])["status"] == "failed", "Payload mutation was not detected")
                require(managers["b"].verify_installed(name, prefix=prefixes["b"])["status"] == "verified", "Mutation escaped the A prefix")
                entry["payload_tamper_detected"] = True
            finally:
                chosen.write_bytes(before)
            recipe = Path(records["a"]["operation"]) / "package" / "recipe"
            helper = next((p for p in recipe.rglob("*") if p.is_file() and not p.is_symlink()), None)
            require(helper is not None, "The tested package has no bound recipe input")
            helper_before = helper.read_bytes()
            try:
                helper.write_bytes(helper_before + b"\nCPG_RECIPE_TAMPER\n")
                rejected = False
                try:
                    managers["a"].check(name, prefix=prefixes["a"])
                except ValueError as error:
                    rejected = "helper files changed" in str(error)
                    entry["recipe_tamper_reason"] = str(error)
                require(rejected, "Mutated recipe was not rejected before execution")
                entry["recipe_tamper_rejected"] = True
            finally:
                helper.write_bytes(helper_before)
            # A failed integrity observation remains in its original receipt.
            # Fresh verification and rechecking are recorded separately here.
            entry["restored_inventory"] = managers["a"].verify_installed(name, prefix=prefixes["a"])
            require(entry["restored_inventory"]["status"] == "verified", "Restored payload differs")
            entry["restored_check"] = managers["a"].check(name, prefix=prefixes["a"])
            require(entry["restored_check"]["status"] == "passed", "Restored resource check failed")
            managers["a"].remove(name, prefix=prefixes["a"])
            require(not prefixes["a"].exists(), "A prefix survived removal")
            entry["b_after_a_remove"] = managers["b"].check(name, prefix=prefixes["b"])
            require(entry["b_after_a_remove"]["status"] == "passed", "A removal damaged B")
            require(managers["b"].verify_installed(name, prefix=prefixes["b"])["status"] == "verified", "B bytes changed after A removal")
            managers["b"].remove(name, prefix=prefixes["b"])
            require(not prefixes["b"].exists(), "B prefix survived removal")
            entry["removed_prefixes"] = [str(prefixes[x]) for x in ("a", "b")]
            entry["status"] = "passed"
            write(output / "summary.json", summary)
        for side, manager in managers.items():
            manager.report(output / side / "report")
        require(Registry.load().to_dict() == original_value, "The original registry changed")
        summary.update(status="passed", baseline_resource_count=len(original),
                       baseline_catalog_digest=original.sha256, original_registry_unchanged=True,
                       package_count=len(summary["packages"]), independent_installs=2 * len(summary["packages"]))
    except BaseException as error:
        summary.update(status="failed", error=repr(error), traceback=traceback.format_exc())
        write(output / "summary.json", summary)
        raise
    write(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.bundle.absolute(), args.output.absolute())
    print(json.dumps({k: v for k, v in result.items() if k != "packages"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
