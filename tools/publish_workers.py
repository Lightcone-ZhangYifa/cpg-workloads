#!/usr/bin/env python3
"""Replay audited text-material archives and publish explicit worker plans.

CPG alone creates packages and qualifies installations. This transport reproduces
already frozen bytes; it cannot create a new package identity or install software.
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
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Lightcone-ZhangYifa/cpg-workloads"
HEX = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
PUBLICATION_FIELDS = {"published", "asset_count", "url", "release_id", "published_at", "verified_assets"}


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_path(name):
    relative = PurePosixPath(name)
    if (not name or relative.is_absolute() or ".." in relative.parts
            or relative.as_posix() != name or "\\" in name):
        raise ValueError("Noncanonical repository path: " + name)
    path = ROOT / relative
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlinks are not allowed in text masters: " + name)
    return path


def load(path):
    path = Path(path)
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("JSON inputs must be ordinary files: " + str(path))
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def tag_name(tag):
    if not re.fullmatch(r"worker-[a-z0-9][a-z0-9._-]*", tag):
        raise ValueError("Worker publication requires an explicit worker-* tag")
    return tag


def artifact_name(spec, method, sha):
    def slug(value, limit):
        original = str(value)
        cleaned = re.sub(r"[^a-zA-Z0-9.+_-]+", "-", original).strip("-.") or "unknown"
        if cleaned != original or len(cleaned) > limit:
            cleaned = cleaned[:limit - 13] + "-" + hashlib.sha256(original.encode()).hexdigest()[:12]
        return cleaned
    target = spec["target"]
    return "cpg--" + "--".join((slug(spec["id"], 60), slug(spec["version"], 40),
        slug(spec["build"], 36), method, slug(target["os"] + "-" + target["arch"], 26), sha[:20])) + ".cpgpkg.tar.gz"


def identity(row):
    return fingerprint({key: row[key] for key in ("id", "version", "build", "method", "target")})


def artifact(sha):
    if not HEX.fullmatch(sha):
        raise ValueError("Invalid artifact checksum")
    record = load(checked_path("catalog/artifacts/" + sha + ".json"))
    template = checked_path(record["template"])
    manifest = load(template / "manifest.json")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("kind") != "compiler_playground_resource_package" or manifest.get("schema_version") != 1
            or fingerprint(unsigned) != manifest.get("manifest_sha256")
            or fingerprint(manifest["files"]) != manifest.get("inventory_sha256")):
        raise ValueError("Frozen CPG manifest fingerprint mismatch")
    spec = manifest["package"]
    if (manifest["method"] != "material" or record.get("text_payload_review", {}).get("status") != "passed"
            or record.get("release_eligible") is not True or record.get("structure") != "passed"
            or record.get("build_check") != "passed" or record.get("functional") != "passed"
            or record.get("metadata_missing") or record.get("source_locks_complete") is not True
            or record.get("sha256") != sha or record.get("manifest_sha256") != manifest["manifest_sha256"]
            or type(record.get("bytes")) is not int or record["bytes"] <= 0):
        raise ValueError("This artifact lacks reviewed text-material qualification")
    if any(record.get(key) != spec[key] for key in ("id", "version", "build", "target")) or record["method"] != manifest["method"]:
        raise ValueError("Artifact record differs from its frozen package identity")
    catalog = spec["metadata"].get("catalog", {})
    if (catalog.get("license_class") != "open" or not catalog.get("license_id")
            or catalog.get("redistributable") is False):
        raise ValueError("The artifact does not declare open redistribution terms")
    q = record.get("qualification", {})
    checks = q.get("checks", {})
    observed = checks.get("results", [])
    declared = {item["id"]: item for item in spec["checks"]}
    if (q.get("status") != "installed" or q.get("installation", {}).get("status") != "installed"
            or checks.get("status") != "passed" or checks.get("functional_status") != "passed"
            or q.get("package_artifact", {}).get("sha256") != sha
            or q.get("package_artifact", {}).get("bytes") != record["bytes"]
            or len(observed) != len(declared) or {item["id"] for item in observed} != set(declared)
            or not any(item["kind"] == "functional" for item in declared.values())):
        raise ValueError("Fresh installation/check evidence does not cover this artifact")
    for result in observed:
        check = declared[result["id"]]
        if result.get("kind") != check["kind"]:
            raise ValueError("Check kind changed")
        if check["kind"] != "hardware" and (result.get("status") != "passed"
                or type(result.get("returncode")) is not int or result["returncode"] != check["expected_returncode"]
                or result.get("timed_out") is not False or result.get("interrupted", False)
                or result.get("stdout_regex") != check.get("stdout_regex")):
            raise ValueError("Declared software check did not pass")
    for section, field in ((q.get("installation", {}), "evidence"), (checks, "results")):
        for result in section.get(field, []):
            logs_required = ((field == "results" and result.get("kind") != "hardware")
                or type(result.get("returncode")) is int
                or (result.get("status") == "passed" and "argv" in result)
                or result.get("timed_out") is True or result.get("interrupted") is True
                or any(name in result for name in ("stdout", "stderr")))
            if not logs_required:
                continue
            for name in ("stdout", "stderr"):
                log = result.get(name)
                if (not isinstance(log, dict) or not isinstance(log.get("retained_path"), str)
                        or not log["retained_path"] or type(log.get("bytes")) is not int
                        or log["bytes"] < 0 or not isinstance(log.get("sha256"), str)
                        or not HEX.fullmatch(log["sha256"])):
                    raise ValueError("Executed installation/check requires retained stdout and stderr logs")
                path = checked_path(record["template"] + "/" + log["retained_path"])
                if (not path.is_file() or path.stat().st_size != log["bytes"]
                        or checksum(path) != log["sha256"]):
                    raise ValueError("Retained installation/check log differs")
    if record.get("asset_name") != artifact_name(spec, manifest["method"], sha):
        raise ValueError("Noncanonical release filename")
    return record, manifest


def replay(record, manifest, output):
    """Write the frozen CPG archive format, accepting only the already audited hash."""
    output = Path(output).absolute()
    if output.is_symlink() or output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Archive output must be outside the source repository")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / record["asset_name"]
    if destination.exists() or destination.is_symlink():
        if destination.is_file() and not destination.is_symlink() and destination.stat().st_size == record["bytes"] and checksum(destination) == record["sha256"]:
            return destination
        raise FileExistsError(destination)
    rows = manifest["files"]
    if len({row["path"] for row in rows}) != len(rows):
        raise ValueError("Duplicate archive member")
    temporary = destination.with_name(destination.name + ".part")
    stream = temporary.open("xb")
    try:
        with stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                raw = encoded(manifest)
                header = tarfile.TarInfo("manifest.json")
                header.mode, header.size, header.mtime = 0o644, len(raw), 0
                archive.addfile(header, io.BytesIO(raw))
                for row in rows:
                    path = checked_path(record["template"] + "/" + row["path"])
                    if PurePosixPath(row["path"]).parts[0] not in {"payload", "recipe", "tools"}:
                        raise ValueError("Text-material archive has an unsupported root")
                    if type(row["mode"]) is not int or not 0 <= row["mode"] <= 0o777:
                        raise ValueError("Invalid archive mode")
                    header = tarfile.TarInfo(row["path"])
                    header.mode, header.mtime = row["mode"], 0
                    if row["kind"] == "directory":
                        if not path.is_dir():
                            raise ValueError("Missing master directory")
                        header.type = tarfile.DIRTYPE
                        archive.addfile(header)
                    elif row["kind"] == "file":
                        data = path.read_bytes()
                        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                            raise ValueError("Master member differs: " + row["path"])
                        data.decode("utf-8")
                        header.size = len(data)
                        archive.addfile(header, io.BytesIO(data))
                    else:
                        raise ValueError("Only reviewed ordinary text files/directories can be replayed")
        if temporary.stat().st_size != record["bytes"] or checksum(temporary) != record["sha256"]:
            raise ValueError("Replay differs from the CPG-created, installed and audited archive")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def validate_receipt(value):
    info = value.get("release", {})
    tag = info.get("tag", "")
    if (value.get("schema_version") != 1 or value.get("kind") != "compiler_playground_package_repository"
            or info.get("published") is not True or info.get("repository") != REPOSITORY
            or not COMMIT.fullmatch(info.get("source_commit", ""))
            or info.get("url") != f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
            or type(info.get("release_id")) is not int or info["release_id"] <= 0
            or not info.get("published_at")):
        raise ValueError("Invalid verified publication receipt")
    assets = info.get("verified_assets", {})
    names, identities = set(), set()
    if not 1 <= len(value["packages"]) <= 950:
        raise ValueError("Invalid publication package count")
    for row in value["packages"]:
        name = artifact_name(row, row["method"], row["sha256"])
        key = identity(row)
        if name in names or key in identities or not HEX.fullmatch(row["sha256"]) or type(row["bytes"]) is not int or row["bytes"] <= 0:
            raise ValueError("Duplicate or invalid published artifact")
        names.add(name); identities.add(key)
        if (row["path"] != "packages/sha256/" + row["sha256"] + ".cpgpkg.tar.gz"
                or row["download_url"] != f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
                or assets.get(name) != {"sha256": row["sha256"], "bytes": row["bytes"]}):
            raise ValueError("Published row differs from the verified asset")
    if set(assets) != names | {"manifest.json", "SHA256SUMS"} or info.get("asset_count") != len(assets):
        raise ValueError("Unexpected asset set in receipt")
    before = {**value, "release": {key: item for key, item in info.items() if key not in PUBLICATION_FIELDS}}
    raw = encoded(before)
    if assets["manifest.json"] != {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}:
        raise ValueError("Receipt is not bound to the uploaded manifest")
    raw = "".join(f"{assets[name]['sha256']}  {name}\n" for name in sorted(names | {"manifest.json"})).encode()
    if assets["SHA256SUMS"] != {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}:
        raise ValueError("Receipt is not bound to the uploaded checksums")


def published():
    rows, releases = {}, []
    for path in sorted((ROOT / "catalog/releases").glob("*.json")):
        value = load(path)
        validate_receipt(value)
        releases.append(value["release"])
        for row in value["packages"]:
            key = identity(row)
            if key in rows and rows[key]["sha256"] != row["sha256"]:
                raise ValueError("Conflicting immutable package identity")
            rows.setdefault(key, row)
    return rows, releases


def build(tag, output):
    tag_name(tag)
    plan = load(checked_path("release-plans/workers/" + tag + ".json"))
    if plan.get("kind") != "cpg_worker_release_plan" or plan.get("tag") != tag or not 1 <= len(plan["artifacts"]) <= 950:
        raise ValueError("Invalid worker release plan")
    previous, _ = published()
    rows, assets, paths, seen = [], [], ["release-plans/workers/" + tag + ".json", "tools/publish_workers.py", ".github/workflows/publish-workers.yml"], set()
    for sha in plan["artifacts"]:
        record, manifest = artifact(sha)
        key = identity(record)
        if key in seen or key in previous and previous[key]["sha256"] != sha:
            raise ValueError("Duplicate/conflicting publication identity")
        seen.add(key)
        assets.append(replay(record, manifest, output))
        paths.extend(("catalog/artifacts/" + sha + ".json", record["template"]))
        rows.append({**{key: record[key] for key in ("id", "version", "build", "target", "method", "sha256", "bytes", "manifest_sha256", "template")},
                     "dependencies": manifest["resolved_dependencies"], "path": "packages/sha256/" + sha + ".cpgpkg.tar.gz",
                     "download_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{record['asset_name']}",
                     "qualification": {key: record[key] for key in ("structure", "build_check", "functional")}})
    value = {"schema_version": 1, "kind": "compiler_playground_package_repository", "packages": rows,
             "release": {"tag": tag, "repository": REPOSITORY, "source_commit": os.environ.get("GITHUB_SHA"), "scope": "numbered worker deliveries"}}
    out = Path(output)
    (out / "manifest.json").write_bytes(encoded(value))
    assets.append(out / "manifest.json")
    (out / "SHA256SUMS").write_text("".join(f"{checksum(path)}  {path.name}\n" for path in sorted(assets)))
    assets.append(out / "SHA256SUMS")
    return value, assets, paths


def gh(*args, missing=False):
    result = subprocess.run(["gh", *args], text=True, capture_output=True)
    if result.returncode:
        if missing and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout) if args[0] == "api" and result.stdout.strip() else result.stdout.strip() or None


def assets_for(release_id):
    result, page = {}, 1
    while True:
        rows = gh("api", f"repos/{REPOSITORY}/releases/{release_id}/assets?per_page=100&page={page}")
        for row in rows:
            if row["name"] in result:
                raise ValueError("Duplicate remote asset name")
            result[row["name"]] = row
        if len(rows) < 100:
            return result
        page += 1


def verify_assets(actual, expected, complete):
    if set(actual) - set(expected) or complete and set(actual) != set(expected):
        raise ValueError("Remote release asset set differs")
    for name, row in actual.items():
        if row.get("state") != "uploaded" or row.get("size") != expected[name]["bytes"] or row.get("digest") != "sha256:" + expected[name]["sha256"]:
            raise ValueError("Remote asset checksum/size/state differs: " + name)


def frozen(commit, paths):
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != commit:
        raise ValueError("Publication checkout differs from the requested source commit")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--", *paths], cwd=ROOT, text=True)
    if dirty:
        raise ValueError("Frozen publication inputs contain uncommitted changes")
    subprocess.run(["git", "fetch", "origin", "main", "--no-tags"], cwd=ROOT, check=True)
    subprocess.run(["git", "merge-base", "--is-ancestor", commit, "FETCH_HEAD"], cwd=ROOT, check=True)
    subprocess.run(["git", "diff", "--exit-code", commit, "FETCH_HEAD", "--", *paths], cwd=ROOT, check=True)
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD", "--", "catalog/releases"], cwd=ROOT, text=True).splitlines()
    tag = os.environ["GITHUB_REF_NAME"].removeprefix("publish-workers/")
    plan = load(checked_path("release-plans/workers/" + tag + ".json"))
    candidates = {identity(record): record["sha256"] for record, _ in (artifact(sha) for sha in plan["artifacts"])}
    for name in names:
        if not name.endswith(".json"):
            continue
        receipt = json.loads(subprocess.check_output(["git", "show", "FETCH_HEAD:" + name], cwd=ROOT, text=True))
        validate_receipt(receipt)
        for row in receipt["packages"]:
            if identity(row) in candidates and candidates[identity(row)] != row["sha256"]:
                raise ValueError("Current main contains a conflicting immutable publication")


def publish(tag, output):
    tag_name(tag)
    commit = os.environ.get("GITHUB_SHA", "")
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF_NAME") != "publish-workers/" + tag or not COMMIT.fullmatch(commit)):
        raise ValueError("Publishing requires an explicit publish-workers/<tag> push")
    value, paths_on_disk, paths = build(tag, output)
    frozen(commit, paths)
    expected = {path.name: {"sha256": checksum(path), "bytes": path.stat().st_size} for path in paths_on_disk}
    existing = gh("api", f"repos/{REPOSITORY}/releases/tags/{tag}", missing=True)
    tag_ref = gh("api", f"repos/{REPOSITORY}/git/ref/tags/{tag}", missing=True)
    if tag_ref and (tag_ref["object"]["type"] != "commit" or tag_ref["object"]["sha"] != commit):
        raise ValueError("Existing immutable tag differs from the source commit")
    if existing is None:
        notes = Path(output) / "release-notes.md"
        notes.write_text(f"# {tag}\n\nAudited numbered-worker material packages, reproduced from unpacked text masters. "
                         "Each asset matches the complete SHA-256 and size of the CPG-created artifact tested locally. "
                         "Reader functionality does not establish compiler execution, official benchmark or hardware qualification.\n")
        gh("release", "create", tag, "--repo", REPOSITORY, "--target", commit, "--title", tag, "--notes-file", str(notes), "--draft")
        existing = gh("api", f"repos/{REPOSITORY}/releases/tags/{tag}")
    if existing.get("tag_name") != tag or existing.get("target_commitish") != commit:
        raise ValueError("Release target differs from the frozen source commit")
    actual = assets_for(existing["id"])
    verify_assets(actual, expected, not existing["draft"])
    for path in paths_on_disk:
        if path.name not in actual:
            gh("release", "upload", tag, "--repo", REPOSITORY, str(path))
    verify_assets(assets_for(existing["id"]), expected, True)
    frozen(commit, paths)
    tag_ref = gh("api", f"repos/{REPOSITORY}/git/ref/tags/{tag}", missing=True)
    if tag_ref and (tag_ref["object"]["type"] != "commit" or tag_ref["object"]["sha"] != commit):
        raise ValueError("Tag changed during upload")
    if existing["draft"]:
        gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest=false")
    final = gh("api", f"repos/{REPOSITORY}/releases/tags/{tag}")
    tag_ref = gh("api", f"repos/{REPOSITORY}/git/ref/tags/{tag}")
    if (final["id"] != existing["id"] or final["draft"] is not False or not final.get("published_at")
            or tag_ref["object"]["type"] != "commit" or tag_ref["object"]["sha"] != commit):
        raise ValueError("Publication is not confirmed at the expected commit")
    verify_assets(assets_for(final["id"]), expected, True)
    value["release"].update(published=True, asset_count=len(expected), url=final["html_url"], release_id=final["id"],
                            published_at=final["published_at"], verified_assets=expected)
    validate_receipt(value)
    (Path(output) / "publication.json").write_bytes(encoded(value))
    print(json.dumps({"tag": tag, "packages": len(value["packages"]), "url": final["html_url"]}))


def record_publication(path):
    value = load(path)
    validate_receipt(value)
    tag = tag_name(value["release"]["tag"])
    target = checked_path("catalog/releases/" + tag + ".json")
    if target.exists() and load(target) != value:
        raise ValueError("Refusing to replace an immutable publication receipt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded(value))
    rows, releases = published()
    root_manifest = checked_path("manifest.json")
    current = load(root_manifest)
    if current.get("kind") != "compiler_playground_package_repository" or current.get("schema_version") != 1:
        raise ValueError("Unexpected root manifest")
    for row in current.get("packages", []):
        if identity(row) not in rows or rows[identity(row)]["sha256"] != row["sha256"]:
            raise ValueError("Existing package rows must have matching verified receipts")
    current["packages"] = sorted(rows.values(), key=lambda row: (row["id"], row["version"], row["build"], row["method"], row["sha256"]))
    current["releases"] = releases
    current.setdefault("policy", {})["scope"] = "pre-worker and numbered-worker delivery migration"
    root_manifest.write_bytes(encoded(current))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "publish"):
        p = sub.add_parser(command); p.add_argument("tag"); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("record"); p.add_argument("receipt", type=Path)
    args = parser.parse_args()
    if args.command == "record":
        record_publication(args.receipt)
    elif args.command == "publish":
        publish(args.tag, args.output)
    else:
        value, assets, _ = build(args.tag, args.output)
        print(json.dumps({"tag": args.tag, "artifacts": len(value["packages"]), "assets": [str(path) for path in assets]}))


if __name__ == "__main__":
    main()
