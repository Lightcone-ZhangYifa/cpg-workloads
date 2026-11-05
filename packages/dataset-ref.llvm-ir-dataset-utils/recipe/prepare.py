#!/usr/bin/env python3
"""Prepare a fixed static source closure using the public CPG APIs."""
from __future__ import annotations

import argparse
import configparser
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Invalid closure-relative path: " + value)
    return path


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def verify_definition(spec, closure):
    if spec["id"] != closure["resource_id"]:
        raise ValueError("Closure belongs to another original resource")
    for key, expected in closure["preserved_definition_fields"].items():
        actual = spec["metadata"]["catalog"] if key == "metadata.catalog" else spec[key]
        if actual != expected:
            raise ValueError("Original definition field changed: " + key)


def archive_view(path):
    files, links, modules, pointers = {}, {}, {}, {}
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        roots = {relative(member.name.rstrip("/")).parts[0] for member in members}
        if len(roots) != 1:
            raise ValueError("A fixed closure archive must have one enclosing directory")
        root = next(iter(roots))
        for member in members:
            parts = relative(member.name.rstrip("/")).parts
            if len(parts) == 1:
                continue
            name = PurePosixPath(*parts[1:]).as_posix()
            if name in files or name in links:
                raise ValueError("Duplicate archive member")
            if member.isfile():
                with archive.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                files[name] = {"sha256": digest, "bytes": member.size}
                if name == ".gitmodules":
                    modules[name] = archive.extractfile(member).read().decode("utf-8")
                if member.size < 1024:
                    data = archive.extractfile(member).read()
                    if data.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                        pointers[name] = data.decode("ascii")
            elif member.issym():
                links[name] = member.linkname
            elif member.islnk():
                raise ValueError("Hard-linked source member needs a separately reviewed profile")
            elif not member.isdir():
                raise ValueError("Special source member is forbidden")
    return {"root": root, "files": files, "links": links,
            "gitmodules": modules.get(".gitmodules"), "lfs": pointers}


def normalize_reviewed_links(source, output, edits):
    """Rewrite only explicitly hash-bound bad upstream link targets."""
    expected = {row["path"]: row for row in edits}
    observed = set()
    before = archive_view(source)
    with tarfile.open(source) as archive, Path(output).open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                for original in archive:
                    member = copy.copy(original)
                    member.pax_headers = dict(original.pax_headers)
                    parts = PurePosixPath(member.name).parts
                    local = PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else "."
                    if local in expected:
                        edit = expected[local]
                        if not member.issym() or member.linkname != edit["old_target"]:
                            raise ValueError("Reviewed original link no longer matches")
                        if before["files"].get(edit["target_path"]) != edit["target_identity"]:
                            raise ValueError("Reviewed in-tree target no longer matches")
                        member.linkname = edit["new_target"]
                        member.pax_headers.pop("linkpath", None)
                        observed.add(local)
                    target.addfile(member, archive.extractfile(original) if original.isfile() else None)
    if observed != set(expected):
        raise ValueError("Not every reviewed link relocation was applied")
    after = archive_view(output)
    if before["files"] != after["files"]:
        raise ValueError("A link relocation changed ordinary upstream file bytes")
    wanted_links = dict(before["links"])
    wanted_links.update({name: edit["new_target"] for name, edit in expected.items()})
    if after["links"] != wanted_links:
        raise ValueError("Unexpected source-link edit")
    return {"original_sha256": sha256(source), "derived_sha256": sha256(output),
            "edits": edits, "all_original_regular_file_bytes_preserved": True}


def verify_gitlinks(view, component, closure, recipe):
    expected = [row for row in closure.get("gitlinks", []) if row["parent_input"] == component["id"]]
    parser = configparser.ConfigParser(interpolation=None)
    if view["gitmodules"]:
        parser.read_string(view["gitmodules"])
    declared = {parser[section]["path"]: parser[section]["url"] for section in parser.sections()}
    if declared != {row["path"]: row["repository_url"] for row in expected}:
        raise ValueError("Fixed .gitmodules declarations differ from the complete declared closure")
    evidence_name = component.get("git_tree_evidence")
    if evidence_name:
        evidence_path = recipe / relative(evidence_name)
        if sha256(evidence_path) != component["git_tree_evidence_sha256"]:
            raise ValueError("Pinned Git tree evidence changed")
        tree = json.loads(evidence_path.read_text())
        if tree.get("truncated") is not False:
            raise ValueError("Incomplete Git tree cannot establish submodule closure")
        found = {row["path"]: row["sha"] for row in tree["tree"] if row["mode"] == "160000"}
        if found != {row["path"]: row["commit"] for row in expected}:
            raise ValueError("Pinned Git mode-160000 entries differ from the declared closure")


def prepare_payload(spec, closure, paths, payload, recipe):
    from compiler_playground.resource_deploy import unpack_archive
    verify_definition(spec, closure)
    material = payload / relative(closure["material_path"])
    transformations = []
    pointer_observations = {}
    verified_files = 0
    for component in closure["inputs"]:
        if component["kind"] != "archive":
            continue
        raw = paths[component["id"]]
        view = archive_view(raw)
        verify_gitlinks(view, component, closure, recipe)
        placement = component["placement"]
        destination = material if placement == "." else material / relative(placement)
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
                raise ValueError("Submodule replacement would overwrite original material")
            destination.rmdir()
        edits = [row for row in closure.get("link_relocations", []) if row["input_id"] == component["id"]]
        if edits:
            derived = payload.parent / (component["id"] + ".reviewed-links.tar.gz")
            transformations.append(normalize_reviewed_links(raw, derived, edits))
            unpack_archive(derived, destination, strip_root=True)
        else:
            unpack_archive(raw, destination, strip_root=True)
        for name, identity in view["files"].items():
            installed = destination / relative(name)
            if installed.is_symlink() or not installed.is_file() or installed.stat().st_size != identity["bytes"] or sha256(installed) != identity["sha256"]:
                raise ValueError("Original regular source file changed during preparation: " + name)
            verified_files += 1
        for name, pointer in view["lfs"].items():
            global_name = name if placement == "." else (PurePosixPath(placement) / name).as_posix()
            pointer_observations[global_name] = pointer
    expected_lfs = {item["placement"]: item for item in closure["inputs"] if item["kind"] == "lfs"}
    if set(pointer_observations) != set(expected_lfs):
        raise ValueError("The fixed archive's LFS pointer set is incomplete or unexpected")
    for name, component in expected_lfs.items():
        if pointer_observations[name] != component["original_pointer"]:
            raise ValueError("Original LFS pointer bytes differ from the declared input lock")
        expected_text = f'version https://git-lfs.github.com/spec/v1\noid sha256:{component["sha256"]}\nsize {component["bytes"]}\n'
        if component["original_pointer"] != expected_text:
            raise ValueError("LFS data lock differs from the original pointer")
        destination = material / relative(name)
        shutil.copyfile(paths[component["id"]], destination)
        if sha256(destination) != component["sha256"] or destination.stat().st_size != component["bytes"]:
            raise ValueError("LFS data changed during independent copy")
    provenance = {
        "format": "cpg-static-closure-provenance-v1", "resource_id": spec["id"],
        "original_source_locks": spec["sources"],
        "fixed_inputs": [{k: v for k, v in item.items() if k not in ("original_pointer",)} for item in closure["inputs"]],
        "gitlinks": closure.get("gitlinks", []), "retained_original_lfs_pointers": pointer_observations,
        "explicit_link_relocations": transformations,
        "original_regular_files_verified_before_lfs_materialization": verified_files,
        "scope": "Complete declared static source closure; native execution, semantic oracles and official benchmark scores are not qualified."
    }
    evidence = payload / "cpg-source-provenance" / (spec["id"] + ".json")
    evidence.parent.mkdir(parents=True)
    evidence.write_text(canonical_json(provenance))
    return provenance


def main():
    from compiler_playground.packages import pack, verify_package
    from compiler_playground.packages.spec import validate_spec
    from compiler_playground.resource_deploy import acquire_file
    from check import snapshot
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", type=Path, default=Path(__file__).resolve().parents[1] / "package.json")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs-json", type=Path, help="Optional private-input-id to exact original local file mapping")
    parser.add_argument("--no-network", action="store_true")
    args = parser.parse_args()
    recipe = args.definition.parent / "recipe"
    closure = json.loads((recipe / "source-closure.json").read_text())
    spec = validate_spec(json.loads(args.definition.read_text()))
    verify_definition(spec, closure)
    overrides = json.loads(args.inputs_json.read_text()) if args.inputs_json else {}
    known = {item["id"] for item in closure["inputs"]}
    if set(overrides) - known:
        raise ValueError("Local input map includes an undeclared input")
    paths, receipts = {}, []
    for item in closure["inputs"]:
        request = {"id": item["id"], "source_url": item["url"], "sha256": item["sha256"],
                   "archive_bytes": item["bytes"], "license_class": item["license_class"]}
        if item["id"] in overrides:
            request["bundled_path"] = str(Path(overrides[item["id"]]).absolute())
        elif args.no_network:
            request["bundled_path"] = str((args.cache / "sha256" / item["sha256"][:2] / item["sha256"]).absolute())
        receipt = {}
        paths[item["id"]] = acquire_file(request, args.cache, receipt=receipt)
        receipts.append({"id": item["id"], **receipt})
    with tempfile.TemporaryDirectory(prefix="cpg-complete-static-") as temporary:
        payload = Path(temporary) / "payload"
        provenance = prepare_payload(spec, closure, paths, payload, recipe)
        expected = json.loads((recipe / "material-manifest.json").read_text())
        if snapshot(payload) != expected["files"]:
            raise ValueError("Reconstructed static payload differs from the reviewed complete inventory")
        result = pack(spec, args.output, method="material", payload=payload, recipe_dir=recipe,
                      provenance={"source_closure_sha256": sha256(recipe / "source-closure.json"),
                                  "qualification_scope": spec["recipe"]["qualification_scope"],
                                  "native_execution": False, "oci_execution": False})
        verify_package(args.output, expected_sha256=result["sha256"], expected_bytes=result["bytes"])
    print(canonical_json({"status": "passed", "resource_id": spec["id"], "artifact": result,
                          "acquisition": receipts, "original_regular_files_verified": provenance["original_regular_files_verified_before_lfs_materialization"]}))


if __name__ == "__main__":
    main()
