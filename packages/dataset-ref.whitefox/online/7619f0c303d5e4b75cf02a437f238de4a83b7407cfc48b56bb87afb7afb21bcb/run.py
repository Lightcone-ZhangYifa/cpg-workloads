#!/usr/bin/env python3
"""Reproduce the exact frozen material artifact through its existing CPG recipe."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import traceback

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["prepare"])
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--framework-path", type=Path)
    p.add_argument("--no-network", action="store_true")
    a = p.parse_args()
    root = Path(__file__).resolve().parent
    output, cache = a.output.resolve(), a.cache.resolve()
    if output.is_relative_to(root) or cache.is_relative_to(root):
        raise ValueError("Output and input cache must be outside the frozen recipe")
    output.mkdir(parents=True, exist_ok=False)
    summary = {"schema_version": 1, "status": "running", "command": a.command,
               "installation_performed": False, "native_execution_qualified": False,
               "dataset_api_qualified": False, "framework_installer_modified": False}
    try:
        descriptor = json.loads((root / "online.json").read_text())
        if descriptor["schema_version"] != 1 or descriptor["kind"] != "cpg_online_material_recipe":
            raise ValueError("Unsupported frozen online recipe")
        actual = []
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if rel == "online.json":
                continue
            mode = stat.S_IMODE(path.lstat().st_mode)
            if path.is_symlink():
                raise ValueError("Online recipe members must be ordinary independent files")
            if path.is_dir():
                actual.append({"path": rel, "kind": "directory", "mode": mode})
            elif path.is_file():
                actual.append({"path": rel, "kind": "file", "mode": mode,
                               "sha256": sha(path), "bytes": path.stat().st_size})
            else:
                raise ValueError("Unsupported online recipe member")
        if actual != descriptor["recipe_files"]:
            raise ValueError("Frozen online recipe has missing, changed or additional members")
        spec = json.loads((root / "package.json").read_text())
        template = json.loads((root / "offline-manifest.json").read_text())
        if spec != template["package"] or spec["id"] != descriptor["resource_id"]:
            raise ValueError("Frozen definition differs from the verified offline manifest")
        if spec["sources"] != descriptor["original_source_locks"]:
            raise ValueError("Canonical discovery source identity changed")
        if template["manifest_sha256"] != descriptor["offline_artifact"]["manifest_sha256"]:
            raise ValueError("Offline manifest identity changed")
        env = {key: value for key, value in os.environ.items() if not key.startswith("LD_")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if a.framework_path:
            framework_src = str(a.framework_path.resolve() / "src")
            sys.path.insert(0, framework_src)
            env["PYTHONPATH"] = framework_src
        from compiler_playground.packages import verify_package
        artifact = output / (spec["id"] + ".material.cpgpkg.tar.gz")
        argv = [sys.executable, "-B", str(root / "recipe/prepare.py"),
                "--definition", str(root / "package.json"), "--cache", str(cache), "--output", str(artifact)]
        if a.no_network:
            argv.append("--no-network")
        process = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=480)
        (output / "prepare.stdout").write_text(process.stdout)
        (output / "prepare.stderr").write_text(process.stderr)
        summary.update(resource_id=spec["id"], recipe_sha256=sha(root / "online.json"),
                       argv=argv, returncode=process.returncode, network_disabled=a.no_network)
        if process.returncode:
            raise RuntimeError("Existing resource preparation failed; see prepare.stderr")
        expected = descriptor["offline_artifact"]
        checked = verify_package(artifact, expected_sha256=expected["sha256"], expected_bytes=expected["bytes"])
        if checked["manifest"] != template:
            raise ValueError("Reproduced offline manifest differs from the frozen original")
        prepared = json.loads(process.stdout)
        summary.update(status="passed", acquisitions=prepared.get("acquisitions", []),
            artifact={"path": artifact.name, "sha256": checked["sha256"], "bytes": checked["bytes"],
                      "manifest_sha256": template["manifest_sha256"]},
            byte_identical_to_offline_artifact=True, complete_recipe_inventory_verified=True)
    except BaseException as error:
        summary.update(status="failed", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary.get(key) for key in ("resource_id", "status", "error")}))
    return 0 if summary["status"] == "passed" else 1

if __name__ == "__main__":
    raise SystemExit(main())
