#!/usr/bin/env python3
"""Reproduce audited package bytes and publish explicit immutable Release plans.

There is no installer here. CPG owns installation and functional qualification;
this script reconstructs an already-audited archive from its source template.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen
import zlib

from import_archives import (artifact_name, qualification_errors, qualification_logs,
                             safe_relative, sha256, source_locks_complete, write_json)

REPOSITORY = "Lightcone-ZhangYifa/cpg-workloads"
ROOT = Path(__file__).resolve().parents[1]
CHECKSUM = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
PUBLICATION_FIELDS = {"published", "asset_count", "url", "release_id", "published_at", "verified_assets"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identity(row):
    return digest({key: row[key] for key in ("id", "version", "build", "method", "target")})


def validate_tag(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", tag):
        raise ValueError("Invalid release tag")
    return tag


def load_json(path):
    path = Path(path)
    if not path.is_file() or any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("JSON inputs must be ordinary files: " + str(path))
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key: " + key)
            value[key] = item
        return value
    return json.loads(path.read_text(), object_pairs_hook=unique)


def load_manifest(template):
    if (template.is_symlink() or (template / "manifest.json").is_symlink()
            or any(parent.is_symlink() for parent in template.parents)):
        raise ValueError("Template manifests must be ordinary source files")
    manifest = load_json(template / "manifest.json")
    claimed = manifest.pop("manifest_sha256")
    if digest(manifest) != claimed:
        raise ValueError("Template manifest fingerprint mismatch")
    manifest["manifest_sha256"] = claimed
    if manifest.get("kind") != "compiler_playground_resource_package" or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported package manifest")
    if digest(manifest["files"]) != manifest["inventory_sha256"]:
        raise ValueError("Template inventory fingerprint mismatch")
    return manifest


def publication_errors(record, manifest):
    """Keep execution evidence honest; permit an explicit trusted static review."""
    if record.get("qualification_mode") != "trusted_delivery_static_review":
        return qualification_errors(record, manifest)
    spec, errors = manifest["package"], []
    for field in ("id", "version", "build", "target"):
        if record.get(field) != spec[field]:
            errors.append("Artifact identity differs from its template: " + field)
    if record.get("method") != manifest["method"] or record.get("manifest_sha256") != manifest["manifest_sha256"]:
        errors.append("Artifact manifest identity differs")
    if (not isinstance(record.get("sha256"), str) or CHECKSUM.fullmatch(record["sha256"]) is None
            or type(record.get("bytes")) is not int or record["bytes"] <= 0):
        errors.append("Artifact byte identity is incomplete")
    if record.get("structure") != "passed" or record.get("metadata_missing") != []:
        errors.append("Static review requires complete metadata and package structure")
    if record.get("source_locks_complete") is not True or not source_locks_complete(manifest):
        errors.append("Effective source locks are incomplete or changed fixed fields")
    catalog = spec["metadata"].get("catalog", {})
    if (catalog.get("license_class") != "open" or not catalog.get("license_id")
            or catalog.get("redistributable") is False):
        errors.append("Public redistribution is not established by the original license metadata")
    review = record.get("static_review", {})
    if (not isinstance(review, dict) or review.get("status") != "passed"
            or review.get("basis") != "trusted_delivery"
            or review.get("artifact_sha256") != record.get("sha256")
            or review.get("manifest_sha256") != manifest["manifest_sha256"]
            or not isinstance(review.get("checks"), dict)
            or any(review["checks"].get(key) != "passed" for key in ("identity", "source_locks", "license"))):
        errors.append("Trusted delivery lacks an identity-bound static review")
    if record.get("build_check") != "not_run" or record.get("functional") != "not_run":
        errors.append("Static trust must not claim unexecuted build or functional checks")
    return errors


def documentation_binaries(record, manifest):
    """Accept only independently reviewed PNG entries bound to the frozen package."""
    review = record.get("documentation_payload_review")
    if review is None:
        if record.get("text_payload_review", {}).get("status") != "passed":
            raise ValueError("Material publication requires a reviewed documentation payload")
        return {}
    files = {row["path"]: row for row in manifest["files"] if row["kind"] == "file"}
    if (not isinstance(review, dict) or review.get("status") != "passed"
            or review.get("source_type") != "pinned_upstream_documentation"
            or type(review.get("file_count")) is not int
            or review["file_count"] != sum(name.startswith("payload/") for name in files)
            or not isinstance(review.get("binary_files"), list)):
        raise ValueError("Invalid reviewed documentation payload")
    approved = {}
    for item in review["binary_files"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid reviewed PNG entry")
        name = safe_relative(item.get("path")).as_posix()
        source = safe_relative(item.get("source_path")).as_posix()
        row = files.get(name)
        if (name in approved or not name.startswith("payload/") or not name.endswith(".png")
                or not source.endswith(".png") or item.get("media_type") != "image/png"
                or row is None or type(row.get("mode")) is not int or row["mode"] & 0o111
                or type(item.get("bytes")) is not int or item["bytes"] <= 0
                or item["bytes"] != row.get("bytes") or item.get("sha256") != row.get("sha256")
                or not isinstance(item.get("sha256"), str) or CHECKSUM.fullmatch(item["sha256"]) is None
                or any(not isinstance(item.get(key), str) or COMMIT.fullmatch(item[key]) is None
                       for key in ("source_commit", "git_blob"))):
            raise ValueError("Reviewed PNG differs from its immutable manifest or source identity")
        approved[name] = item
    return approved


def verify_png(data):
    """Check PNG signature, chunk boundaries/CRCs and complete image framing."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Reviewed binary is not a PNG")
    offset, seen_header, image_bytes = 8, False, 0
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind, end = data[offset + 4:offset + 8], offset + 12 + length
        if end > len(data) or not re.fullmatch(rb"[A-Za-z]{4}", kind):
            raise ValueError("Invalid PNG chunk boundary")
        payload = data[offset + 8:end - 4]
        if zlib.crc32(kind + payload) & 0xffffffff != int.from_bytes(data[end - 4:end], "big"):
            raise ValueError("PNG chunk checksum differs")
        if not seen_header and kind != b"IHDR":
            raise ValueError("PNG must start with IHDR")
        if kind == b"IHDR":
            if (seen_header or length != 13 or not int.from_bytes(payload[:4], "big")
                    or not int.from_bytes(payload[4:8], "big") or payload[10:12] != b"\0\0"
                    or payload[12] not in (0, 1)):
                raise ValueError("Invalid PNG image header")
            seen_header = True
        elif kind == b"IDAT":
            image_bytes += length
        elif kind == b"IEND":
            if length or not image_bytes or end != len(data):
                raise ValueError("Invalid PNG ending or trailing data")
            return
        offset = end
    raise ValueError("PNG has no complete IEND")


def material_member(template, row, binaries):
    relative = safe_relative(row["path"])
    path = template / relative
    if (relative.parts[0] not in {"recipe", "tools", "payload"}
            or type(row.get("mode")) is not int or not 0 <= row["mode"] <= 0o777
            or any(item.is_symlink() for item in (path, *path.parents))):
        raise ValueError("Invalid ordinary material member: " + row["path"])
    if row["kind"] == "directory":
        if not path.is_dir():
            raise ValueError("Missing material directory: " + row["path"])
        return None
    if row["kind"] != "file" or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Material members must be ordinary files or directories")
    data = path.read_bytes()
    if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("Material member differs from its frozen inventory: " + row["path"])
    if row["path"] in binaries:
        if path.stat().st_mode & 0o111:
            raise ValueError("Reviewed PNG master has executable permissions")
        verify_png(data)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != binaries[row["path"]]["git_blob"]:
            raise ValueError("Reviewed PNG differs from its source Git blob")
    else:
        data.decode("utf-8")
        if b"\0" in data:
            raise ValueError("Unlisted binary content in material member: " + row["path"])
    return data


def verify_material(record, manifest, template):
    binaries = documentation_binaries(record, manifest)
    names = [row["path"] for row in manifest["files"]]
    if len(names) != len(set(names)) or "manifest.json" in names:
        raise ValueError("Duplicate or reserved material member")
    for row in manifest["files"]:
        material_member(template, row, binaries)
    return binaries


def checked_record(checksum):
    if not isinstance(checksum, str) or CHECKSUM.fullmatch(checksum) is None:
        raise ValueError("Invalid artifact checksum")
    path = ROOT / "catalog/artifacts" / (checksum + ".json")
    if path.is_symlink():
        raise ValueError("Artifact records must be ordinary source files")
    record = load_json(path)
    manifest = load_manifest(ROOT / safe_relative(record["template"]))
    if record.get("sha256") != checksum:
        raise ValueError("Artifact catalog identity mismatch")
    if record.get("release_eligible") is not True:
        raise ValueError("Unqualified artifact cannot enter a Release")
    problems = publication_errors(record, manifest)
    if problems:
        raise ValueError("; ".join(problems))
    verify_evidence(record, ROOT / safe_relative(record["template"]))
    if manifest["method"] == "material":
        verify_material(record, manifest, ROOT / safe_relative(record["template"]))
    if record.get("asset_name") != artifact_name(manifest["package"], manifest["method"], checksum):
        raise ValueError("Noncanonical artifact filename")
    return record


def verify_evidence(record, template):
    """Validate retained execution logs before trusting a passing qualification."""
    for log in qualification_logs(record.get("qualification", {})):
        relative = safe_relative(log.get("retained_path"))
        if relative.as_posix() != "evidence/" + log["sha256"] + ".log":
            raise ValueError("Qualification log has a noncanonical retained path")
        path = template / relative
        if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents)
                or not path.is_file() or path.stat().st_size != log["bytes"]
                or sha256(path) != log["sha256"]):
            raise ValueError("Retained execution evidence differs from the manager receipt")


def check_publication_receipt(value, tag):
    """Bind an index receipt to the exact manifest and assets verified remotely."""
    validate_tag(tag)
    info = value.get("release", {})
    if (value.get("schema_version") != 1 or value.get("kind") != "compiler_playground_package_repository"
            or info.get("published") is not True or info.get("tag") != tag
            or info.get("repository") != REPOSITORY
            or COMMIT.fullmatch(info.get("source_commit", "")) is None
            or info.get("url") != f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
            or type(info.get("release_id")) is not int or info["release_id"] <= 0
            or not isinstance(info.get("published_at"), str) or not info["published_at"]):
        raise ValueError("Unverified or mismatched publication receipt: " + tag)
    packages, assets = value.get("packages"), info.get("verified_assets")
    if not isinstance(packages, list) or not 1 <= len(packages) <= 950 or not isinstance(assets, dict):
        raise ValueError("A publication receipt needs its package rows and verified assets")
    names, identities = set(), set()
    for row in packages:
        checksum, size = row.get("sha256"), row.get("bytes")
        if (not isinstance(checksum, str) or CHECKSUM.fullmatch(checksum) is None
                or type(size) is not int or size <= 0):
            raise ValueError("Published package hash or size is invalid")
        name = artifact_name(row, row["method"], checksum)
        key = identity(row)
        if name in names or key in identities:
            raise ValueError("Duplicate package identity in publication receipt")
        names.add(name)
        identities.add(key)
        if (row.get("path") != "packages/sha256/" + checksum + ".cpgpkg.tar.gz"
                or row.get("download_url") != f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
                or assets.get(name) != {"sha256": checksum, "bytes": size}):
            raise ValueError("Published row differs from its verified Release asset")
    if set(assets) != names | {"manifest.json", "SHA256SUMS"} or info.get("asset_count") != len(assets):
        raise ValueError("Publication receipt has an incomplete or unexpected asset set")
    original = {**value, "release": {key: item for key, item in info.items() if key not in PUBLICATION_FIELDS}}
    payload = (json.dumps(original, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    if assets["manifest.json"] != {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}:
        raise ValueError("Publication receipt differs from the verified Release manifest")
    checksums = "".join(f"{assets[name]['sha256']}  {name}\n" for name in sorted(names | {"manifest.json"})).encode()
    if assets["SHA256SUMS"] != {"sha256": hashlib.sha256(checksums).hexdigest(), "bytes": len(checksums)}:
        raise ValueError("Publication receipt differs from the verified Release checksums")


def published_rows(receipts=None):
    """Return one canonical row per immutable identity from all verified receipts."""
    rows, releases = {}, []
    if receipts is None:
        paths = sorted((ROOT / "catalog/releases").glob("*.json"))
        if any(path.is_symlink() for path in paths):
            raise ValueError("Publication receipts must be ordinary source files")
        receipts = ((path.stem, load_json(path)) for path in paths)
    for tag, value in receipts:
        check_publication_receipt(value, tag)
        info = value["release"]
        releases.append(info)
        for row in value["packages"]:
            key = identity(row)
            previous = rows.get(key)
            if previous is not None:
                # Equal bytes can appear in an older release; retain the first URL.
                if {k: v for k, v in previous.items() if k != "download_url"} != {
                        k: v for k, v in row.items() if k != "download_url"}:
                    raise ValueError("Conflicting published bytes or metadata under one package identity")
            else:
                rows[key] = row
    return rows, releases


def source_file(source, cache, *, network):
    checksum, size = source.get("sha256"), source.get("bytes")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum) or type(size) is not int or size < 0:
        raise ValueError("Acquisition needs a complete exact source lock")
    target = cache / checksum
    if target.exists():
        if target.is_symlink() or target.stat().st_size != size or sha256(target) != checksum:
            raise ValueError("Cached input differs from its exact source lock")
        return target
    if not network:
        raise FileNotFoundError("Locked source is absent from the explicit cache: " + checksum)
    url = source.get("url")
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Acquisition requires a credential-free HTTPS source URL")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=checksum + ".", suffix=".part", dir=cache, delete=False) as staged:
        temporary = Path(staged.name)
    try:
        with urlopen(url, timeout=90) as response, temporary.open("wb") as output:
            final_url = urlparse(response.geturl())
            if (final_url.scheme != "https" or not final_url.netloc
                    or final_url.username or final_url.password or final_url.fragment):
                raise ValueError("Source redirected to an unsafe URL")
            observed = 0
            while block := response.read(1024 * 1024):
                observed += len(block)
                if observed > size:
                    raise ValueError("Source exceeds its locked byte size")
                output.write(block)
        if observed != size or sha256(temporary) != checksum:
            raise ValueError("Downloaded source differs from its exact lock")
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or target.stat().st_size != size or sha256(target) != checksum:
                raise FileExistsError("Refusing to overwrite different cached source bytes")
        return target
    finally:
        temporary.unlink(missing_ok=True)


def rebuild(record, output, cache, *, network=False):
    template = ROOT / safe_relative(record["template"])
    manifest = load_manifest(template)
    spec, method = manifest["package"], manifest["method"]
    if method not in {"wrapper", "source", "material"}:
        raise ValueError("This template needs its separately reviewed payload reproducer")
    problems = publication_errors(record, manifest)
    if record.get("release_eligible") is not True or problems:
        raise ValueError("Unqualified artifact: " + "; ".join(problems))
    verify_evidence(record, template)
    binaries = verify_material(record, manifest, template) if method == "material" else {}
    sources = {}
    if method == "source":
        locks = manifest.get("resolved_sources", spec["sources"])
        for source in locks:
            sources["sources/" + source["sha256"]] = source_file(source, cache, network=network)
    rows = manifest["files"]
    names = [row["path"] for row in rows]
    if len(names) != len(set(names)) or "manifest.json" in names:
        raise ValueError("Duplicate or reserved template path")
    payload = (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    destination = output / artifact_name(spec, method, record["sha256"])
    output.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Release output must not be a symlink")
    if destination.exists():
        if destination.stat().st_size == record["bytes"] and sha256(destination) == record["sha256"]:
            return destination
        raise FileExistsError("Refusing to overwrite different release bytes")
    with tempfile.NamedTemporaryFile(prefix="cpg-rebuild-", suffix=".part", dir=output, delete=False) as staged:
        temporary = Path(staged.name)
    try:
        with temporary.open("wb") as stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                info = tarfile.TarInfo("manifest.json")
                info.mode, info.size, info.mtime = 0o644, len(payload), 0
                archive.addfile(info, io.BytesIO(payload))
                for row in rows:
                    relative = safe_relative(row["path"])
                    allowed_roots = {"recipe", "tools", "payload"} if method == "material" else {"recipe", "tools", "sources"}
                    if relative.parts[0] not in allowed_roots:
                        raise ValueError("Source/wrapper templates must not carry an installed payload")
                    info = tarfile.TarInfo(row["path"])
                    info.mode, info.mtime = row["mode"], 0
                    if row["kind"] == "directory":
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    elif row["kind"] == "symlink":
                        if method == "material":
                            raise ValueError("Material members must not be symlinks")
                        link = PurePosixPath(row["target"])
                        if link.is_absolute() or ".." in link.parts:
                            raise ValueError("Recipe links need a separately reviewed reproducer")
                        info.type, info.linkname = tarfile.SYMTYPE, row["target"]
                        archive.addfile(info)
                    elif row["kind"] == "file":
                        if method == "material":
                            data = material_member(template, row, binaries)
                            info.size = len(data)
                            archive.addfile(info, io.BytesIO(data))
                            continue
                        source = sources.get(row["path"], template / relative)
                        if source.is_symlink() or source.stat().st_size != row["bytes"] or sha256(source) != row["sha256"]:
                            raise ValueError("Template member differs from its original inventory: " + row["path"])
                        info.size = row["bytes"]
                        with source.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        raise ValueError("Unknown template member type")
        if temporary.stat().st_size != record["bytes"] or sha256(temporary) != record["sha256"]:
            raise ValueError("Rebuilt archive differs from its independently audited original")
        # Another publisher may have filled this output while we rebuilt.
        # Hard-link creation is atomic and cannot overwrite its bytes.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if (destination.is_symlink() or destination.stat().st_size != record["bytes"]
                    or sha256(destination) != record["sha256"]):
                raise FileExistsError("Refusing to overwrite different release bytes")
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def repository_row(record, tag):
    manifest = load_manifest(ROOT / safe_relative(record["template"]))
    spec = manifest["package"]
    dependencies = manifest["resolved_dependencies"]
    if manifest["method"] == "binary":
        build_only = set(spec["dependencies"]["build"]) - set(
            spec["dependencies"]["run"] + spec["dependencies"]["system"])
        dependencies = [row for row in dependencies if row["id"] not in build_only]
    qualification = {key: record[key] for key in ("structure", "build_check", "functional")}
    if record.get("qualification_mode") == "trusted_delivery_static_review":
        qualification.update(qualification_mode=record["qualification_mode"], static_review=record["static_review"])
    return {**{key: spec[key] for key in ("id", "version", "build", "target")},
            "method": manifest["method"], "sha256": record["sha256"], "bytes": record["bytes"],
            "manifest_sha256": manifest["manifest_sha256"], "dependencies": dependencies,
            "path": "packages/sha256/" + record["sha256"] + ".cpgpkg.tar.gz",
            "download_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{record['asset_name']}",
            "qualification": qualification,
            "template": record["template"]}


def plan_software(prefix, batch_size):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", prefix) or not 1 <= batch_size <= 950:
        raise ValueError("Invalid release prefix or batch size")
    published, _ = published_rows()
    planned = set()
    selected = {key: row["sha256"] for key, row in published.items()}
    for path in sorted((ROOT / "release-plans").glob("*.json")):
        value = load_plan(path.stem)
        planned.update(value["artifacts"])
        for checksum in value["artifacts"]:
            record = checked_record(checksum)
            key = identity(record)
            if key in selected and selected[key] != checksum:
                raise ValueError("Different planned bytes share an immutable package identity; increment build")
            selected[key] = checksum
    records = [json.loads(path.read_text()) for path in sorted((ROOT / "catalog/artifacts").glob("*.json"))]
    records = sorted((checked_record(row["sha256"]) for row in records
                      if row.get("release_eligible") and row["method"] in {"wrapper", "source", "material"}
                      and row["sha256"] not in planned
                      and not (identity(row) in published and published[identity(row)]["sha256"] == row["sha256"])),
                     key=lambda row: (row["id"], row["version"], row["build"], row["method"], row["sha256"]))
    for record in records:
        key = identity(record)
        if key in selected and selected[key] != record["sha256"]:
            raise ValueError("Different artifact bytes share an immutable package identity; increment build")
        selected[key] = record["sha256"]
    groups = {}
    for row in records:
        groups.setdefault((row["id"], row["version"], row["build"]), []).append(row)
    for software, artifacts in groups.items():
        if len(artifacts) > batch_size:
            raise ValueError("Software release exceeds the selected asset limit")
        tag = validate_tag(prefix + "-" + "-".join(re.sub(r"[^a-z0-9._-]+", "-", str(item).lower())
                                                 for item in software))
        plan = {"schema_version": 1, "kind": "cpg_workload_release_plan", "tag": tag,
                "repository": REPOSITORY, "artifacts": [row["sha256"] for row in artifacts]}
        path = ROOT / "release-plans" / (tag + ".json")
        if path.exists() and json.loads(path.read_text()) != plan:
            raise FileExistsError("An existing release plan is immutable")
        write_json(path, plan)
    print(json.dumps({"eligible": len(records), "plans": len(groups)}))


def load_plan(tag):
    validate_tag(tag)
    path = ROOT / "release-plans" / (tag + ".json")
    if path.is_symlink():
        raise ValueError("Publication plans must be ordinary source files")
    plan = load_json(path)
    artifacts = plan.get("artifacts")
    if (plan.get("schema_version") != 1 or plan.get("kind") != "cpg_workload_release_plan"
            or plan.get("tag") != tag or plan.get("repository") != REPOSITORY
            or not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 950
            or any(not isinstance(item, str) or CHECKSUM.fullmatch(item) is None for item in artifacts)):
        raise ValueError("Invalid publication plan")
    if len(artifacts) != len(set(artifacts)):
        raise ValueError("Duplicate planned artifact")
    return plan


def build_plan(tag, output, *, network, source_commit=None):
    output = Path(output).absolute()
    if output.resolve().is_relative_to(ROOT.resolve()) or output.is_symlink():
        raise ValueError("Build output must be an ordinary directory outside the source checkout")
    plan = load_plan(tag)
    rows, assets = [], []
    published, _ = published_rows()
    identities = {key: row["sha256"] for key, row in published.items()}
    records = [checked_record(checksum) for checksum in plan["artifacts"]]
    for record in records:
        key = identity(record)
        if key in identities and identities[key] != record["sha256"]:
            raise ValueError("Conflicting immutable package identity in publication plan")
        identities[key] = record["sha256"]
    if len({identity(record) for record in records}) != len(records):
        raise ValueError("Duplicate package identity in publication plan")
    for record in records:
        destination = rebuild(record, output, output / ".source-cache", network=network)
        assets.append(destination)
        rows.append(repository_row(record, tag))
    manifest = {"schema_version": 1, "kind": "compiler_playground_package_repository", "packages": rows,
                "release": {"tag": tag, "repository": REPOSITORY,
                            "source_commit": source_commit or os.environ.get("GITHUB_SHA"),
                            "scope": "historical workload deliveries"}}
    write_json(output / "manifest.json", manifest)
    assets.append(output / "manifest.json")
    (output / "SHA256SUMS").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sorted(assets)))
    assets.append(output / "SHA256SUMS")
    return plan, manifest, assets


def gh(*arguments, json_output=False, check=True, input_data=None):
    result = subprocess.run(["gh", *arguments], text=True, capture_output=True, check=False,
                            input=None if input_data is None else json.dumps(input_data, allow_nan=False))
    if check and result.returncode:
        raise RuntimeError("GitHub operation failed: " + result.stderr.strip())
    if not check and result.returncode:
        if "HTTP 404" in result.stderr:
            return None
        raise RuntimeError("GitHub lookup failed: " + result.stderr.strip())
    return json.loads(result.stdout) if json_output else result.stdout


def release_for(tag):
    # Drafts need not resolve through releases/tags. Find one unique object,
    # then use only its numeric ID for all mutations and subsequent reads.
    pages = gh("api", "--paginate", "--slurp", f"repos/{REPOSITORY}/releases?per_page=100", json_output=True)
    matches = [row for page in pages for row in page if row.get("tag_name") == tag]
    if len(matches) > 1:
        raise ValueError("Multiple releases use the requested tag")
    return matches[0] if matches else None


def upload_endpoint(release):
    identifier = release.get("id")
    if type(identifier) is not int or identifier <= 0:
        raise ValueError("Release API did not return a numeric ID")
    expected = f"https://uploads.github.com/repos/{REPOSITORY}/releases/{identifier}/assets"
    if release.get("upload_url") not in (expected, expected + "{?name,label}"):
        raise ValueError("Release upload URL differs from the canonical repository and ID")
    return expected


def verify_release(release, tag, commit, *, release_id=None):
    if (release.get("tag_name") != tag or release.get("target_commitish") != commit
            or type(release.get("draft")) is not bool
            or release_id is not None and release.get("id") != release_id):
        raise ValueError("Release API identity or source commit differs")
    upload_endpoint(release)


def release_assets(release_id):
    pages = gh("api", "--paginate", "--slurp",
               f"repos/{REPOSITORY}/releases/{release_id}/assets?per_page=100", json_output=True)
    rows = [row for page in pages for row in page]
    names = [row["name"] for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("Remote Release contains duplicate asset names")
    return {row["name"]: row for row in rows}


def verify_assets(actual, expected, *, complete):
    if set(actual) - set(expected) or complete and set(actual) != set(expected):
        raise ValueError("Release asset set differs from the explicit publication plan")
    for name, row in actual.items():
        if (row.get("state") != "uploaded" or row["size"] != expected[name]["bytes"]
                or row.get("digest") != "sha256:" + expected[name]["sha256"]):
            raise ValueError("Uploaded asset hash, size, or state differs: " + name)


def verify_release_commit(tag, commit, *, missing=False):
    result = gh("api", f"repos/{REPOSITORY}/git/ref/tags/{tag}", json_output=True, check=not missing)
    if result is None and missing:
        return
    ref = result["object"]
    for _ in range(8):
        if ref["type"] == "commit":
            if ref["sha"] != commit:
                raise ValueError("Release tag points to a different source commit")
            return
        if ref["type"] != "tag":
            break
        ref = gh("api", f"repos/{REPOSITORY}/git/tags/{ref['sha']}", json_output=True)["object"]
    raise ValueError("Release tag does not resolve to an ordinary source commit")


def verify_publication_source(commit, main, tag):
    """Allow queued software releases when main has not changed their inputs."""
    plan_path = "release-plans/" + tag + ".json"
    plan = load_plan(tag)
    # The plan, catalog and templates pin artifact bytes. A publisher or CI fix
    # may resume the same immutable data from a newer committed checkout.
    paths = [plan_path]
    records = []
    for checksum in plan["artifacts"]:
        record = checked_record(checksum)
        records.append(record)
        paths.extend(("catalog/artifacts/" + checksum + ".json", record["template"]))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--",
                            "tools", ".github", "tests/test_release_pipeline.py", *paths],
                           cwd=ROOT, check=True, capture_output=True, text=True).stdout
    if head != os.environ.get("GITHUB_SHA", commit) or dirty:
        raise ValueError("Publication requires the exact committed source and unchanged publication inputs")
    if subprocess.run(["git", "diff", "--quiet", commit, "HEAD", "--", *paths], cwd=ROOT).returncode:
        raise ValueError("Current checkout differs from the Release's frozen publication data")
    if main == commit:
        return
    subprocess.run(["git", "fetch", "--no-tags", "origin", "main"], cwd=ROOT, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "FETCH_HEAD"], cwd=ROOT)
    if ancestor.returncode:
        raise ValueError("Publication source must belong to the current main history")
    unchanged = subprocess.run(["git", "diff", "--quiet", commit, "FETCH_HEAD", "--", *paths], cwd=ROOT)
    if unchanged.returncode:
        raise ValueError("Publication inputs changed on main; request publication from the current commit")
    # Queued releases may follow another software's index commit. Inspect that new
    # immutable index as well, without checking out or overwriting either tree.
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD", "--", "catalog/releases"],
                           cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
    receipts = []
    for name in names:
        if not name.endswith(".json"):
            continue
        raw = subprocess.run(["git", "show", "FETCH_HEAD:" + name], cwd=ROOT,
                             check=True, capture_output=True, text=True).stdout
        receipts.append((PurePosixPath(name).stem, json.loads(raw)))
    published, _ = published_rows(receipts)
    for record in records:
        previous = published.get(identity(record))
        if previous is not None and previous["sha256"] != record["sha256"]:
            raise ValueError("Current main already published different bytes for this package identity")


def publish(tag, output):
    validate_tag(tag)
    repository, ref, commit = (os.environ.get(name, "") for name in ("GITHUB_REPOSITORY", "GITHUB_REF_NAME", "GITHUB_SHA"))
    if repository != REPOSITORY or ref != "publish/" + tag or COMMIT.fullmatch(commit) is None:
        raise ValueError("Publication requires an explicit publish/<tag> push in the canonical repository")
    existing = release_for(tag)
    if existing is not None:
        commit = existing.get("target_commitish", "")
        if not isinstance(commit, str) or COMMIT.fullmatch(commit) is None:
            raise ValueError("Existing Release does not pin an exact source commit")
        verify_release(existing, tag, commit)
    main = gh("api", f"repos/{REPOSITORY}/git/ref/heads/main", json_output=True)["object"]["sha"]
    verify_publication_source(commit, main, tag)
    plan, manifest, assets = build_plan(tag, output, network=True, source_commit=commit)
    output = Path(output)
    notes = output / "release-notes.md"
    notes.write_text(f"# {tag}\n\nReproduces {len(plan['artifacts'])} audited CPG artifacts from unpacked source templates.\n\n"
                     "Every published asset matches the previously verified complete SHA-256 and byte size. "
                     "APT wrappers are metadata-only and carry an explicit functional-test exemption. "
                     "Each artifact records its review scope; a static review does not claim a new build or functional run. "
                     "Trusted deliveries retain build_check=not_run and functional=not_run.\n\n"
                     "Use the pinned manifest with Compiler Playground's existing package manager. "
                     "This release does not claim unexecuted hardware or official benchmark qualification.\n")
    verify_release_commit(tag, commit, missing=True)
    if existing is None:
        existing = gh("api", "--method", "POST", f"repos/{REPOSITORY}/releases", "--input", "-",
                      json_output=True, input_data={"tag_name": tag, "target_commitish": commit,
                                                   "name": tag, "body": notes.read_text(),
                                                   "draft": True, "make_latest": "false"})
    verify_release(existing, tag, commit)
    release_id = existing["id"]
    endpoint = f"repos/{REPOSITORY}/releases/{release_id}"
    existing = gh("api", endpoint, json_output=True)
    verify_release(existing, tag, commit, release_id=release_id)
    # Draft tags need not exist until publication. Existing public tags must match.
    if not existing["draft"]:
        verify_release_commit(tag, commit)
    by_name = release_assets(existing["id"])
    expected = {path.name: {"sha256": sha256(path), "bytes": path.stat().st_size} for path in assets}
    if len(expected) != len(assets):
        raise ValueError("Release asset filenames collide")
    verify_assets(by_name, expected, complete=not existing["draft"])
    missing = [path for path in assets if path.name not in by_name]
    upload_url = upload_endpoint(existing)
    for number, path in enumerate(missing, 1):
        uploaded_asset = gh("api", "--method", "POST", upload_url + "?" + urlencode({"name": path.name}),
                            "-H", "Content-Type: application/octet-stream", "--input", str(path),
                            json_output=True)
        if uploaded_asset.get("name") != path.name:
            raise ValueError("Upload response returned a different asset name")
        verify_assets({path.name: uploaded_asset}, {path.name: expected[path.name]}, complete=True)
        if number % 25 == 0 or number == len(missing):
            print(json.dumps({"tag": tag, "uploaded": number, "total": len(missing)}), flush=True)
    actual = release_assets(existing["id"])
    verify_assets(actual, expected, complete=True)
    if existing["draft"]:
        # Uploads can take a long time. Recheck both the inputs and any tag just
        # before the irreversible public transition, not only at job startup.
        main = gh("api", f"repos/{REPOSITORY}/git/ref/heads/main", json_output=True)["object"]["sha"]
        verify_publication_source(commit, main, tag)
        verify_release_commit(tag, commit, missing=True)
        latest = gh("api", endpoint, json_output=True)
        verify_release(latest, tag, commit, release_id=release_id)
        if latest["draft"]:
            gh("api", "--method", "PATCH", endpoint, "--input", "-", json_output=True,
               input_data={"draft": False, "make_latest": "false"})
    uploaded = gh("api", endpoint, json_output=True)
    verify_release(uploaded, tag, commit, release_id=release_id)
    if uploaded["id"] != existing["id"] or uploaded.get("draft") is not False or not uploaded.get("published_at"):
        raise ValueError("Release has not been confirmed public")
    verify_release_commit(tag, commit)
    verify_assets(release_assets(uploaded["id"]), expected, complete=True)
    manifest["release"].update(published=True, asset_count=len(assets), url=uploaded["html_url"],
                               release_id=uploaded["id"], published_at=uploaded["published_at"],
                               verified_assets=expected)
    check_publication_receipt(manifest, tag)
    write_json(output / "publication.json", manifest)
    print(json.dumps({"tag": tag, "packages": len(manifest["packages"]), "url": uploaded["html_url"]}))


def merge_manifest():
    rows, releases = published_rows()
    previous = load_json(ROOT / "manifest.json")
    if any(identity(row) not in rows for row in previous.get("packages", [])):
        raise ValueError("Refusing to remove an existing package without a matching publication receipt")
    value = {**previous, "schema_version": 1, "kind": "compiler_playground_package_repository",
             "repository": "https://github.com/" + REPOSITORY,
             "packages": sorted(rows.values(), key=lambda row: (row["id"], row["version"], row["build"], row["method"], row["sha256"])),
             "releases": releases, "online_recipes": previous.get("online_recipes", []),
             "policy": {**previous.get("policy", {}),
                        "git": "Unpacked definitions, build recipes, tests, provenance and manifests only",
                        "release": "Verified immutable artifacts; no silent fallback to untested variants",
                        "historical_resource_denominator": 1862, "scope": "individual software package publication"}}
    write_json(ROOT / "manifest.json", value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--prefix", required=True)
    plan.add_argument("--batch-size", type=int, default=500)
    build = sub.add_parser("build")
    build.add_argument("tag")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--network", action="store_true")
    release = sub.add_parser("publish")
    release.add_argument("tag")
    release.add_argument("--output", type=Path, required=True)
    sub.add_parser("manifest")
    args = parser.parse_args()
    if args.command == "plan":
        plan_software(args.prefix, args.batch_size)
    elif args.command == "build":
        plan, manifest, assets = build_plan(args.tag, args.output, network=args.network)
        print(json.dumps({"tag": args.tag, "packages": len(plan["artifacts"]), "assets": len(assets)}))
    elif args.command == "publish":
        publish(args.tag, args.output)
    else:
        value = merge_manifest()
        print(json.dumps({"published_packages": len(value["packages"]), "releases": len(value["releases"])}))


if __name__ == "__main__":
    main()
