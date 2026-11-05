#!/usr/bin/env python3
"""Fetch one frozen public input and reproduce its exact existing material artifact.

This is an external maintainer recipe, not an additional CPG installation
method. It preserves original licensing metadata and grants no new legal,
native-execution, Dataset, benchmark or OCI qualification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import traceback
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


def public_receipt_url(value):
    parsed=urlsplit(value)
    return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,"",""))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    if path.suffix == ".gz":
        with path.open("wb") as stream, gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as out:
            out.write(raw)
    else:
        path.write_bytes(raw)


def safe_path(value):
    require(isinstance(value, str), "Recipe paths must be strings")
    path = PurePosixPath(value)
    require(value and not path.is_absolute() and ".." not in path.parts and path.as_posix() == value,
            "Recipe paths must be canonical relative paths")
    return path


def public_https(url):
    parsed = urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment,
            "Only public HTTPS input URLs without credentials or fragments are supported")


def load_recipe(directory):
    directory = Path(directory).resolve(strict=True)
    recipe = json.loads((directory / "online.json").read_text())
    require(recipe.get("schema_version") == 1 and recipe.get("kind") == "cpg_online_material_recipe",
            "Unsupported online recipe contract")
    expected_paths = set()
    for row in recipe["recipe_files"]:
        relative = safe_path(row["path"])
        path = directory / relative
        require(not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(directory),
                "Online recipe member is missing or unsafe")
        require(path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], "Online recipe member identity differs")
        expected_paths.add(relative.as_posix())
    actual_paths = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    require(actual_paths == expected_paths | {"online.json"}, "Online recipe has missing or undeclared files")
    template = json.loads((directory / "offline-manifest.json").read_text())
    require(template["method"] == "material" and template["package"]["id"] == recipe["resource_id"], "Wrong material artifact template")
    require(template["manifest_sha256"] == recipe["offline_artifact"]["manifest_sha256"], "Manifest identity differs")
    require(template["package"]["sources"] == recipe["original_source_locks"], "Original source lock changed")
    require(template["package"]["metadata"]["catalog"] == recipe["original_catalog"], "Original catalog or license facts changed")
    require(len(recipe["original_source_locks"]) == 1, "This reviewed layout requires exactly one complete original archive")
    audit_path = directory / "recipe/input-audit.json"
    audit = json.loads(audit_path.read_text())
    require(audit["status"] == "passed" and audit["resource_id"] == recipe["resource_id"], "Acquisition audit not admitted")
    require(audit["original_sources"] == recipe["original_source_locks"], "Acquisition audit original source mismatch")
    require(audit["resolved_sources"] == recipe["resolved_acquisition_locks"], "Acquisition audit resolved source mismatch")
    require(sha(audit_path) == recipe["source_lock_extension_audit_sha256"] == template["provenance"]["source_lock_extension_audit"], "Acquisition audit identity mismatch")
    require(len(recipe["resolved_acquisition_locks"]) == 1, "Expected one audited acquisition lock")
    original = recipe["original_source_locks"][0]
    resolved = recipe["resolved_acquisition_locks"][0]
    require((original["sha256"] is None) == (original["bytes"] is None), "Inconsistent original source lock")
    require(all((value is None and key in ("sha256", "bytes")) or resolved[key] == value for key,value in original.items()), "Resolved lock changed an originally fixed source field")
    require(template["package"]["recipe"]["acquisition_lock"] == resolved, "Material definition acquisition lock differs")
    additional=recipe.get("additional_acquisition_locks", [])
    require(additional == audit.get("additional_acquisition_locks", []) == template["package"]["recipe"].get("additional_acquisition_locks", []), "Supplemental acquisition locks differ")
    for lock in recipe["resolved_acquisition_locks"] + additional:
        public_https(lock["url"])
        require(lock["extract"] is False and type(lock["bytes"]) is int and lock["bytes"] > 0, "Invalid opaque-file input contract")
        safe_path(lock["material_path"])
    require(not additional and recipe["layout"] == template["package"]["recipe"]["material_representation"] == "original_locked_file_container" and recipe["source_tree_deployment"] is False, "Opaque file representation changed")
    return recipe, template


def fetch_source(lock, cache_directory, receipt, *, allow_network=True, timeout=60):
    """Use the unchanged shared DownloadCache with one bounded HTTPS fetch."""
    from compiler_playground.downloads import DownloadCache
    public_https(lock["url"])
    receipt.update(status="running", original_url=lock["url"], expected_sha256=lock["sha256"],
                   expected_bytes=lock["bytes"], network_used=False, cache_hit=False,
                   full_input_verified=False, downloaded_bytes=0)
    cache = DownloadCache(cache_directory)

    def fetch(target):
        require(allow_network, "Exact input is absent from cache and network retrieval was disabled")
        receipt["network_used"] = True
        request = Request(lock["url"], headers={"User-Agent": "compiler-playground-online-material/0.21.4"})
        digest, copied = hashlib.sha256(), 0
        with urlopen(request, timeout=timeout) as response, Path(target).open("wb") as output:
            final_url = response.geturl()
            public_https(final_url)
            receipt.update(resolved_url=public_receipt_url(final_url), resolved_url_query_omitted=bool(urlsplit(final_url).query), http_status=getattr(response, "status", None),
                           content_length=response.headers.get("Content-Length"),
                           content_type=response.headers.get("Content-Type"))
            while True:
                block = response.read(min(1024 * 1024, lock["bytes"] - copied + 1))
                if not block:
                    break
                copied += len(block)
                receipt["downloaded_bytes"] = copied
                require(copied <= lock["bytes"], "HTTP response exceeds the exact original input byte count")
                output.write(block)
                digest.update(block)
        receipt["observed_sha256"] = digest.hexdigest()
        require(copied == lock["bytes"], "HTTP response is incomplete relative to the original byte count")
        require(digest.hexdigest() == lock["sha256"], "Downloaded input SHA-256 differs from the original lock")

    try:
        path, hit = cache.get_or_fetch(lock["sha256"], lock["bytes"], fetch)
        receipt.update(status="passed", cache_hit=hit, path=str(path), full_input_verified=True,
                       sha256=sha(path), bytes=path.stat().st_size,
                       qualification_stage="complete_original_input_identity")
        return path
    except BaseException as exc:
        receipt.update(status="failed", error_type=type(exc).__name__, error=str(exc),
                       qualification_stage="input_not_admitted")
        raise


def probe_source(lock, receipt, *, limit, timeout):
    """Read a bounded HTTP prefix without publishing any partial cache object."""
    public_https(lock["url"])
    limit = min(limit, lock["bytes"])
    request = Request(lock["url"], headers={"User-Agent": "compiler-playground-online-material/0.21.4",
                                          "Range": "bytes=0-" + str(limit - 1)})
    with urlopen(request, timeout=timeout) as response:
        public_https(response.geturl())
        data = response.read(limit)
        receipt.update(status="observed", original_url=lock["url"], resolved_url=public_receipt_url(response.geturl()), resolved_url_query_omitted=bool(urlsplit(response.geturl()).query),
                       http_status=getattr(response, "status", None), requested_prefix_bytes=limit,
                       observed_prefix_bytes=len(data), prefix_sha256=hashlib.sha256(data).hexdigest(),
                       content_range=response.headers.get("Content-Range"), full_input_verified=False,
                       cache_object_published=False, offline_artifact_qualification=False,
                       qualification_stage="partial_transport_observation_only")


def prepare_artifact(recipe, template, directory, raw, work, output, *, discard=False, cache=None):
    from compiler_playground.packages import pack, verify_package
    from compiler_playground.packages.archive import inventory
    from compiler_playground.resource_deploy import unpack_archive
    lock = recipe["resolved_acquisition_locks"][0]
    payload = work / "payload"
    additional=recipe.get("additional_acquisition_locks", [])
    if not lock["extract"]:
        import importlib.util
        module_spec=importlib.util.spec_from_file_location("cpg_file_material", directory / "recipe/file_material.py")
        assembly=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(assembly)
        assembly.assemble(raw,lock,additional,cache,payload)
    elif additional:
        import importlib.util
        module_spec=importlib.util.spec_from_file_location("cpg_material_assembly", directory / ("recipe/archive_set.py" if template["package"]["recipe"].get("material_representation") == "complete_original_archive_set_container" else "recipe/material_assembly.py"))
        assembly=importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(assembly)
        assembly.assemble(raw, lock, additional, cache, payload)
    else:
        unpack_archive(raw, payload, strip_root=lock.get("strip_root", True))
    payload_mode = next(r["mode"] for r in template["files"] if r["path"] == "payload")
    payload.chmod(payload_mode)
    expected_payload = [{**row, "path": row["path"][8:]} for row in template["files"] if row["path"].startswith("payload/")]
    actual_payload = inventory(payload)
    require(actual_payload == expected_payload, "Complete original material differs from the existing offline artifact inventory")
    archive = work / (recipe["resource_id"] + ".material.cpgpkg.tar.gz")
    recipe_dir = directory / "recipe"
    tools_dir = directory / "tools"
    packed = pack(template["package"], archive, method="material", payload=payload,
                  recipe_dir=recipe_dir if recipe_dir.is_dir() else None,
                  tools_dir=tools_dir if tools_dir.is_dir() else None,
                  prefix=template["prefix_policy"]["prefix"],
                  provenance=template["provenance"], resolved_dependencies=template["resolved_dependencies"])
    expected = recipe["offline_artifact"]
    checked = verify_package(archive, expected_sha256=expected["sha256"], expected_bytes=expected["bytes"])
    require(checked["manifest"] == template, "Reproduced offline manifest differs from its historical identity")
    target = None
    if not discard:
        target = output / archive.name
        require(not target.exists(), "Offline artifact output already exists")
        shutil.copyfile(archive, target)
        require(sha(target) == expected["sha256"] and target.stat().st_ino != archive.stat().st_ino,
                "Independent offline artifact copy differs")
    return {"status": "passed", "method": "material", "sha256": packed["sha256"], "bytes": packed["bytes"],
            "path": str(target) if target else None, "byte_identical_to_existing_offline_artifact": True,
            "manifest_sha256": template["manifest_sha256"],
            "payload_files": sum(r["kind"] == "file" for r in actual_payload),
            "payload_symlinks": sum(r["kind"] == "symlink" for r in actual_payload),
            "payload_logical_bytes": sum(r.get("bytes", 0) for r in actual_payload),
            "temporary_reproduction_discarded_after_inventory": discard,
            "qualification_stage": "complete_offline_artifact_reproduction", "installation_or_execution_performed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fetch", "prepare", "probe"])
    parser.add_argument("--recipe", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--framework-path", type=Path, help="Optional source checkout; otherwise use the installed compiler-playground library")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--probe-bytes", type=int, default=65536)
    parser.add_argument("--discard-offline-after-verification", action="store_true")
    args = parser.parse_args(argv)
    require(args.timeout > 0 and args.probe_bytes > 0, "Timeout and byte budget must be positive")
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.framework_path:
        sys.path.insert(0, str(args.framework_path.resolve() / "src"))
    directory, output, cache = args.recipe.resolve(), args.output.resolve(), args.cache.resolve()
    require(not output.is_relative_to(directory) and not cache.is_relative_to(directory), "Runtime outputs must be outside the immutable recipe directory")
    output.mkdir(parents=True, exist_ok=False)
    work = None
    summary = {"schema_version": 1, "release": "0.21.4", "status": "running", "command": args.command,
               "started_utc": datetime.now(timezone.utc).isoformat(), "acquisition": {},
               "native_execution": False, "official_benchmark_score": False, "oci_execution": False,
               "new_functional_qualification": False, "new_dataset_qualification": False,
               "production_package_code_modified": False}
    code = 1
    try:
        recipe, template = load_recipe(directory)
        import compiler_playground
        summary.update(resource_id=recipe["resource_id"], recipe_sha256=sha(directory / "online.json"),
                       framework_version=getattr(compiler_playground, "__version__", "unreported"),
                       original_source_locks=recipe["original_source_locks"],
                       resolved_acquisition_locks=recipe["resolved_acquisition_locks"],
                       source_lock_extension_audit_sha256=recipe["source_lock_extension_audit_sha256"],
                       original_license_facts={k: recipe["original_catalog"].get(k) for k in ("license_class", "license_id", "redistributable")})
        if args.command == "probe":
            require(not args.no_network, "A transport probe requires network access")
            probe_source(recipe["resolved_acquisition_locks"][0], summary["acquisition"], limit=args.probe_bytes, timeout=args.timeout)
        else:
            raw = fetch_source(recipe["resolved_acquisition_locks"][0], cache, summary["acquisition"],
                               allow_network=not args.no_network, timeout=args.timeout)
            summary["supplemental_acquisitions"] = []
            for supplemental_lock in recipe.get("additional_acquisition_locks", []):
                supplemental_receipt = {"id": supplemental_lock["id"], "destination": supplemental_lock["destination"]}
                summary["supplemental_acquisitions"].append(supplemental_receipt)
                fetch_source(supplemental_lock, cache, supplemental_receipt, allow_network=not args.no_network, timeout=args.timeout)
            if args.command == "prepare":
                work = Path(tempfile.mkdtemp(prefix="cpg-online-material-", dir="/tmp"))
                summary["offline_artifact"] = prepare_artifact(recipe, template, directory, raw, work, output,
                                                               discard=args.discard_offline_after_verification, cache=cache)
        summary["status"] = "passed"
        code = 0
    except BaseException as exc:
        summary.update(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
                       error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        if work is not None:
            from compiler_playground.packages.archive import inventory
            cleanup = {"root": str(work), "files": inventory(work),
                       "reason": "Reproducible material copies and byte-identical artifact; exact evidence retained before deletion"}
            write(output / "removed-work-tree.json.gz", cleanup)
            shutil.rmtree(work)
            summary["runtime_cleanup"] = {"status": "completed", "root": str(work), "absent": not work.exists()}
        summary["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write(output / "summary.json", summary)
    print(json.dumps({k: summary.get(k) for k in ("resource_id", "status", "command", "error")}, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
