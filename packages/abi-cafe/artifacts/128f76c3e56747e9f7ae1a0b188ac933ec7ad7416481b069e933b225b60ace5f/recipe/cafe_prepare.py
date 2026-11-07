#!/usr/bin/env python3
"""CPG source recipe: independent offline Rust SDK, build and installation."""
from __future__ import annotations
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    if sys.flags.optimize:
        raise RuntimeError("Optimized Python is not permitted for validation recipes")
    recipe = Path(__file__).resolve().parent
    assets, build, prefix = (p.resolve() for p in (args.assets, args.build, args.prefix))
    if any(x == y or x in y.parents or y in x.parents for i, x in enumerate((assets, build, prefix)) for y in (assets, build, prefix)[i + 1:]):
        raise ValueError("Source assets, build and installed prefix must be independent trees")
    if not 1 <= args.jobs <= 4:
        raise ValueError("jobs must be between 1 and 4")
    bundle = assets / "integration/abi-cafe-integration.tar.gz"
    resource = build / "recipe-inputs"
    resource.mkdir()
    with tarfile.open(bundle) as archive:
        archive.extractall(resource, filter="data")
    (resource / "source").mkdir(exist_ok=True)
    source_lock = json.loads((recipe / "source-inputs.json").read_text())
    for row in source_lock["inputs"]:
        source = assets / "raw" / Path(row["path"]).name
        if source.stat().st_size != row["size"]:
            raise ValueError("Original source size mismatch")
        shutil.copy2(source, resource / row["path"])
    rust_inputs = build / "rust-inputs"
    rust_inputs.mkdir()
    # Share only verified immutable original archives. Never write metadata
    # into the manager's source-assets tree, and never share an installed SDK.
    rust_lock = json.loads((recipe / "rust-components.json").read_text())
    for row in rust_lock:
        original = assets / "rust" / row["url"].rsplit("/", 1)[-1]
        if hashlib.file_digest(original.open("rb"), "sha256").hexdigest() != row["sha256"]:
            raise ValueError("Rust component identity mismatch")
        try:
            os.link(original, rust_inputs / original.name)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            shutil.copy2(original, rust_inputs / original.name)
    shutil.copy2(recipe / "rust-components.json", rust_inputs / "rust-components.json")
    sdk = build / "sdk"
    subprocess.run([sys.executable, "-B", str(recipe / "install-sdk.py"), "--kind", "rust", "--inputs", str(rust_inputs), "--prefix", str(sdk)], check=True)
    stage = build / "stage"
    compile_root = build / "compile"
    subprocess.run([sys.executable, "-B", str(recipe / "build-offline.py"), "--root", str(resource),
                    "--sdk", str(sdk / "rust"), "--work", str(compile_root), "--prefix", str(stage), "--jobs", str(args.jobs)], check=True)
    shutil.copytree(stage, prefix, dirs_exist_ok=True)
    shutil.copytree(sdk / "rust", prefix / "toolchain", symlinks=True)
    shutil.copytree(resource / "source", prefix / "source")
    provenance = json.loads((compile_root / "build-result.json").read_text())
    (prefix / "build-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    # Retain the original maintainer-build observation and add the identity of
    # this independently rebuilt installation, without changing source locks.
    source_observation = prefix / "sources-lock.json"
    if source_observation.exists():
        value = json.loads(source_observation.read_text())
        value["maintainer_binary_sha256"] = value.pop("binary_sha256", None)
        value["installed_binary_sha256"] = hashlib.sha256((prefix / "bin/abi-cafe").read_bytes()).hexdigest()
        value["installation_method"] = "independent_source_build"
        source_observation.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps({"status": "passed", "source_commit": source_lock["commit"],
                      "vendored_crates": source_lock["vendor_crates"], "prefix": str(prefix),
                      "source_build": True, "shared_mutable_build_tree": False,
                      "network_guard": os.environ.get("CPG_OFFLINE_GUARD")}, sort_keys=True))


if __name__ == "__main__":
    main()
