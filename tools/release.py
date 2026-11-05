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
import subprocess
import tarfile
import tempfile
from urllib.parse import urlparse, quote
from urllib.request import urlopen

from import_archives import (artifact_name, qualification_errors, qualification_logs,
                             safe_relative, sha256, write_json)

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


def load_manifest(template):
    if (template.is_symlink() or (template / "manifest.json").is_symlink()
            or any(parent.is_symlink() for parent in template.parents)):
        raise ValueError("Template manifests must be ordinary source files")
    manifest = json.loads((template / "manifest.json").read_text())
    claimed = manifest.pop("manifest_sha256")
    if digest(manifest) != claimed:
        raise ValueError("Template manifest fingerprint mismatch")
    manifest["manifest_sha256"] = claimed
    if manifest.get("kind") != "compiler_playground_resource_package" or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported package manifest")
    if digest(manifest["files"]) != manifest["inventory_sha256"]:
        raise ValueError("Template inventory fingerprint mismatch")
    return manifest


def checked_record(checksum):
    if not isinstance(checksum, str) or CHECKSUM.fullmatch(checksum) is None:
        raise ValueError("Invalid artifact checksum")
    path = ROOT / "catalog/artifacts" / (checksum + ".json")
    if path.is_symlink():
        raise ValueError("Artifact records must be ordinary source files")
    record = json.loads(path.read_text())
    manifest = load_manifest(ROOT / safe_relative(record["template"]))
    if record.get("sha256") != checksum:
        raise ValueError("Artifact catalog identity mismatch")
    if record.get("release_eligible") is not True:
        raise ValueError("Unqualified artifact cannot enter a Release")
    problems = qualification_errors(record, manifest)
    if problems:
        raise ValueError("; ".join(problems))
    verify_evidence(record, ROOT / safe_relative(record["template"]))
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
        receipts = ((path.stem, json.loads(path.read_text())) for path in paths)
    for tag, value in receipts:
        check_publication_receipt(value, tag)
        info = value["release"]
        releases.append(info)
        for row in value["packages"]:
            key = identity(row)
            previous = rows.get(key)
            if previous is not None:
                # Equal bytes can appear in an older batch; retain the first URL.
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
    if method not in {"wrapper", "source"}:
        raise ValueError("This template needs its separately reviewed payload reproducer")
    problems = qualification_errors(record, manifest)
    if record.get("release_eligible") is not True or problems:
        raise ValueError("Unqualified artifact: " + "; ".join(problems))
    verify_evidence(record, template)
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
                    if relative.parts[0] not in {"recipe", "tools", "sources"}:
                        raise ValueError("Source/wrapper templates must not carry an installed payload")
                    info = tarfile.TarInfo(row["path"])
                    info.mode, info.mtime = row["mode"], 0
                    if row["kind"] == "directory":
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    elif row["kind"] == "symlink":
                        link = PurePosixPath(row["target"])
                        if link.is_absolute() or ".." in link.parts:
                            raise ValueError("Recipe links need a separately reviewed reproducer")
                        info.type, info.linkname = tarfile.SYMTYPE, row["target"]
                        archive.addfile(info)
                    elif row["kind"] == "file":
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
    return {**{key: spec[key] for key in ("id", "version", "build", "target")},
            "method": manifest["method"], "sha256": record["sha256"], "bytes": record["bytes"],
            "manifest_sha256": manifest["manifest_sha256"], "dependencies": dependencies,
            "path": "packages/sha256/" + record["sha256"] + ".cpgpkg.tar.gz",
            "download_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{record['asset_name']}",
            "qualification": {key: record[key] for key in ("structure", "build_check", "functional")},
            "template": record["template"]}


def plan_batches(prefix, batch_size):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", prefix) or not 1 <= batch_size <= 950:
        raise ValueError("Invalid release prefix or batch size")
    published, _ = published_rows()
    planned, existing = set(), []
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
        if path.stem.startswith(prefix + "-"):
            suffix = path.stem[len(prefix) + 1:]
            if suffix.isdigit():
                existing.append(int(suffix))
    records = [json.loads(path.read_text()) for path in sorted((ROOT / "catalog/artifacts").glob("*.json"))]
    records = sorted((checked_record(row["sha256"]) for row in records
                      if row.get("release_eligible") and row["method"] in {"wrapper", "source"}
                      and row["sha256"] not in planned
                      and not (identity(row) in published and published[identity(row)]["sha256"] == row["sha256"])),
                     key=lambda row: (row["id"], row["version"], row["build"], row["method"], row["sha256"]))
    for record in records:
        key = identity(record)
        if key in selected and selected[key] != record["sha256"]:
            raise ValueError("Different artifact bytes share an immutable package identity; increment build")
        selected[key] = record["sha256"]
    first_number = max(existing, default=0) + 1
    for offset in range(0, len(records), batch_size):
        tag = f"{prefix}-{first_number + offset // batch_size:03d}"
        plan = {"schema_version": 1, "kind": "cpg_workload_release_plan", "tag": tag,
                "repository": REPOSITORY, "artifacts": [row["sha256"] for row in records[offset:offset + batch_size]]}
        path = ROOT / "release-plans" / (tag + ".json")
        if path.exists() and json.loads(path.read_text()) != plan:
            raise FileExistsError("An existing release plan is immutable")
        write_json(path, plan)
    print(json.dumps({"eligible": len(records), "plans": (len(records) + batch_size - 1) // batch_size}))


def load_plan(tag):
    validate_tag(tag)
    path = ROOT / "release-plans" / (tag + ".json")
    if path.is_symlink():
        raise ValueError("Publication plans must be ordinary source files")
    plan = json.loads(path.read_text())
    artifacts = plan.get("artifacts")
    if (plan.get("schema_version") != 1 or plan.get("kind") != "cpg_workload_release_plan"
            or plan.get("tag") != tag or plan.get("repository") != REPOSITORY
            or not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 950
            or any(not isinstance(item, str) or CHECKSUM.fullmatch(item) is None for item in artifacts)):
        raise ValueError("Invalid publication plan")
    if len(artifacts) != len(set(artifacts)):
        raise ValueError("Duplicate planned artifact")
    return plan


def build_plan(tag, output, *, network):
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
                            "source_commit": os.environ.get("GITHUB_SHA"), "scope": "historical workload deliveries"}}
    write_json(output / "manifest.json", manifest)
    assets.append(output / "manifest.json")
    (output / "SHA256SUMS").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sorted(assets)))
    assets.append(output / "SHA256SUMS")
    return plan, manifest, assets


def gh(*arguments, json_output=False, check=True):
    result = subprocess.run(["gh", *arguments], text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError("GitHub operation failed: " + result.stderr.strip())
    if not check and result.returncode:
        if "HTTP 404" in result.stderr:
            return None
        raise RuntimeError("GitHub lookup failed: " + result.stderr.strip())
    return json.loads(result.stdout) if json_output else result.stdout


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
    """Allow queued batches when main advanced only outside this frozen build."""
    if main == commit:
        return
    subprocess.run(["git", "fetch", "--no-tags", "origin", "main"], cwd=ROOT, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "FETCH_HEAD"], cwd=ROOT)
    if ancestor.returncode:
        raise ValueError("Publication source must belong to the current main history")
    plan_path = "release-plans/" + tag + ".json"
    plan = load_plan(tag)
    paths = ["tools", ".github", "tests/test_release_pipeline.py", plan_path]
    records = []
    for checksum in plan["artifacts"]:
        record = checked_record(checksum)
        records.append(record)
        paths.extend(("catalog/artifacts/" + checksum + ".json", record["template"]))
    unchanged = subprocess.run(["git", "diff", "--quiet", commit, "FETCH_HEAD", "--", *paths], cwd=ROOT)
    if unchanged.returncode:
        raise ValueError("Publication inputs changed on main; request publication from the current commit")
    # Queued batches may follow another batch's index commit. Inspect that new
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
    main = gh("api", f"repos/{REPOSITORY}/git/ref/heads/main", json_output=True)["object"]["sha"]
    verify_publication_source(commit, main, tag)
    plan, manifest, assets = build_plan(tag, output, network=True)
    notes = output / "release-notes.md"
    notes.write_text(f"# {tag}\n\nReproduces {len(plan['artifacts'])} audited CPG artifacts from unpacked source templates.\n\n"
                     "Every published asset matches the previously verified complete SHA-256 and byte size. "
                     "APT wrappers are metadata-only and carry an explicit functional-test exemption. "
                     "Each artifact records its review scope; a static review does not claim a new build or functional run.\n\n"
                     "Use the pinned manifest with Compiler Playground's existing package manager. "
                     "This release does not claim unexecuted hardware or official benchmark qualification.\n")
    existing = gh("api", f"repos/{REPOSITORY}/releases/tags/{tag}", json_output=True, check=False)
    if existing is None:
        # GitHub does not resolve an unpublished draft through the tag endpoint.
        pages = gh("api", "--paginate", "--slurp",
                   f"repos/{REPOSITORY}/releases?per_page=100", json_output=True)
        matches = [row for page in pages for row in page if row.get("tag_name") == tag]
        if len(matches) > 1:
            raise ValueError("Multiple releases use the requested tag")
        existing = matches[0] if matches else None
    verify_release_commit(tag, commit, missing=True)
    if existing is None:
        existing = gh("api", "--method", "POST", f"repos/{REPOSITORY}/releases",
                      "-f", "tag_name=" + tag, "-f", "target_commitish=" + commit,
                      "-f", "name=" + tag, "-f", "body=" + notes.read_text(),
                      "-F", "draft=true", "-f", "make_latest=false", json_output=True)
    elif existing.get("target_commitish") != commit:
        raise ValueError("Existing release has a different source commit")
    if existing.get("tag_name") != tag:
        raise ValueError("Release API returned a different tag")
    # Draft tags need not exist until publication. Existing public tags must match.
    if not existing["draft"]:
        verify_release_commit(tag, commit)
    by_name = release_assets(existing["id"])
    expected = {path.name: {"sha256": sha256(path), "bytes": path.stat().st_size} for path in assets}
    if len(expected) != len(assets):
        raise ValueError("Release asset filenames collide")
    verify_assets(by_name, expected, complete=not existing["draft"])
    missing = [path for path in assets if path.name not in by_name]
    upload_url = f"https://uploads.github.com/repos/{REPOSITORY}/releases/{existing['id']}/assets"
    for number, path in enumerate(missing, 1):
        uploaded_asset = gh("api", "--method", "POST", upload_url + "?name=" + quote(path.name, safe=""),
                            "-H", "Content-Type: application/octet-stream", "--input", str(path),
                            json_output=True)
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
        gh("api", "--method", "PATCH", f"repos/{REPOSITORY}/releases/{existing['id']}",
           "-F", "draft=false", "-f", "make_latest=false", json_output=True)
    uploaded = gh("api", f"repos/{REPOSITORY}/releases/{existing['id']}", json_output=True)
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
    value = {"schema_version": 1, "kind": "compiler_playground_package_repository",
             "repository": "https://github.com/" + REPOSITORY,
             "packages": sorted(rows.values(), key=lambda row: (row["id"], row["version"], row["build"], row["method"], row["sha256"])),
             "releases": releases, "online_recipes": [],
             "policy": {"git": "Unpacked definitions, build recipes, tests, provenance and manifests only",
                        "release": "Verified immutable artifacts; no silent fallback to untested variants",
                        "historical_resource_denominator": 1862, "scope": "historical workload delivery migration"}}
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
        plan_batches(args.prefix, args.batch_size)
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
