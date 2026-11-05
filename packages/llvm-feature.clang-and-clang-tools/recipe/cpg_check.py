#!/usr/bin/env python3
"""Verify immutable package inputs before executing the installed capability."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import uuid

RECIPE = Path(__file__).resolve().parent


def check_files(root: Path, rows: list[dict], *, allow_symlinks: bool) -> dict:
    root = root.resolve(strict=True)
    checked_bytes = 0
    for row in rows:
        relative = PurePosixPath(row["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Invalid trusted input lock path")
        path = root / relative
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not path.is_file():
            raise ValueError("Locked input is absent or escapes its bound prefix: " + str(relative))
        if not allow_symlinks and (path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root)):
            raise ValueError("Installed payload paths must be independent ordinary files")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != row["sha256"]:
            raise ValueError("Locked input hash mismatch: " + str(relative))
        checked_bytes += path.stat().st_size
    return {"status": "verified", "files": len(rows), "bytes_hashed": checked_bytes}


def run(prefix: Path, llvm_root: Path, output_base: Path, mode: str) -> dict:
    payload_lock = json.loads((RECIPE / "payload-lock.json").read_text())
    payload = check_files(prefix, payload_lock["files"], allow_symlinks=False)
    if mode == "integrity":
        return {"status": "passed", "scope": "installed_payload_integrity_only", "payload": payload}
    bindings = json.loads((RECIPE / "toolchain-bindings.json").read_text())
    baseline = check_files(llvm_root, bindings["baseline"]["files"], allow_symlinks=True)
    cir_value = os.environ.get("CPG_CLANG_CIR_ROOT")
    if not cir_value:
        raise ValueError("Explicit CPG_CLANG_CIR_ROOT is required; no runtime download or implicit compiler substitution")
    cir_root = Path(cir_value)
    if not cir_root.is_absolute():
        raise ValueError("CPG_CLANG_CIR_ROOT must be an absolute prepared prefix")
    cir = check_files(cir_root, bindings["cir"]["files"], allow_symlinks=True)
    sys.path.insert(0, str(prefix.resolve()))
    from clang_capabilities import validate
    output_base.mkdir(parents=True, exist_ok=True)
    result = validate(llvm_root, output_base / uuid.uuid4().hex,
                      cir_root=cir_root, cir_pin=bindings["cir"]["source_pin"])
    return {"status": result["status"], "scope": "baseline_tooling_and_clangd_plus_explicit_cir_variant",
            "payload": payload, "external_bindings": {"baseline": baseline, "cir": cir},
            "capability_report": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--llvm-root", type=Path, required=True)
    parser.add_argument("--output-base", type=Path, required=True)
    parser.add_argument("--mode", choices=["integrity", "functional"], default="functional")
    options = parser.parse_args()
    try:
        report = run(options.prefix, options.llvm_root, options.output_base, options.mode)
    except Exception as exc:
        print(json.dumps({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "passed" else 1)
