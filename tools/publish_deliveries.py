#!/usr/bin/env python3
"""Statically import and publish one explicitly requested, encrypted delivery batch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile

import import_archives
import release
from secure_transfer import TransferError, receive


def git(*args, data=None, env=None, check=True):
    result = subprocess.run(["git", *args], input=data, env=env, capture_output=True)
    if check and result.returncode:
        raise RuntimeError("Git operation failed: " + args[0])
    return result


def checked_copy(stream, target, row):
    checksum, size = hashlib.sha256(), 0
    with target.open("xb") as output:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > row["bytes"]:
                raise ValueError("Delivered member exceeds its exact size lock")
            checksum.update(block)
            output.write(block)
    if size != row["bytes"] or checksum.hexdigest() != row["sha256"]:
        raise ValueError("Delivered member differs from its full SHA-256/size lock")


def members(archive, rows, scratch):
    """Yield only explicitly planned regular files, with no tree extraction."""
    for row in rows:
        if (not isinstance(row.get("sha256"), str) or release.CHECKSUM.fullmatch(row["sha256"]) is None
                or type(row.get("bytes")) is not int or not 0 < row["bytes"] < 2 * 1024 ** 3):
            raise ValueError("A requested artifact lacks a valid complete SHA-256/size lock")
    names = [row.get("member") for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate requested archive member")
    if names == [None]:
        row = rows[0]
        if archive.stat().st_size != row["bytes"] or import_archives.sha256(archive) != row["sha256"]:
            raise ValueError("Direct delivery differs from its requested artifact")
        yield archive, row
        return
    wanted = {}
    for row in rows:
        import_archives.safe_relative(row["member"])
        if not 0 < row["bytes"] < 2 * 1024 ** 3:
            raise ValueError("A requested asset is outside GitHub's individual-asset limit")
        wanted[row["member"]] = row
    found = set()
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as handle:
            entries = handle.infolist()
            if len({entry.filename for entry in entries}) != len(entries):
                raise ValueError("Duplicate ZIP member path")
            for entry in entries:
                if entry.filename not in wanted:
                    continue
                row = wanted[entry.filename]
                if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size != row["bytes"]:
                    raise ValueError("Requested ZIP member is not the expected regular file")
                target = scratch / row["sha256"]
                with handle.open(entry) as stream:
                    checked_copy(stream, target, row)
                found.add(entry.filename)
                try:
                    yield target, row
                finally:
                    target.unlink(missing_ok=True)
    else:
        with import_archives.open_outer_tar(archive) as handle:
            seen = set()
            for entry in handle:
                name = entry.name[2:] if entry.name.startswith("./") else entry.name
                if name in seen:
                    raise ValueError("Duplicate TAR member path")
                seen.add(name)
                if name not in wanted:
                    continue
                row = wanted[name]
                if not entry.isreg() or entry.issparse() or entry.size != row["bytes"]:
                    raise ValueError("Requested TAR member is not the expected regular file")
                target = scratch / row["sha256"]
                with handle.extractfile(entry) as stream:
                    checked_copy(stream, target, row)
                found.add(name)
                try:
                    yield target, row
                finally:
                    target.unlink(missing_ok=True)
    if found != set(wanted):
        raise ValueError("One or more explicitly requested members were absent")


def commit_files(paths, message):
    """Commit only named public source paths on top of current main, with FF retries."""
    paths = sorted(set(paths))
    allowed = ("packages/", "catalog/artifacts/", "catalog/imports/", "release-plans/")
    for path in paths:
        import_archives.safe_relative(path)
        if not path.startswith(allowed) or not (release.ROOT / path).is_file():
            raise ValueError("Unexpected file in source-only import commit")
    env = dict(os.environ, GIT_AUTHOR_NAME="github-actions[bot]",
               GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
               GIT_COMMITTER_NAME="github-actions[bot]",
               GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
    for _ in range(5):
        git("fetch", "--no-tags", "origin", "main")
        parent = git("rev-parse", "FETCH_HEAD").stdout.decode().strip()
        with tempfile.TemporaryDirectory(prefix="cpg-source-index-") as folder:
            index_env = dict(env, GIT_INDEX_FILE=str(Path(folder) / "index"))
            git("read-tree", parent, env=index_env)
            for path in paths:
                raw = (release.ROOT / path).read_bytes()
                old = git("show", parent + ":" + path, check=False)
                if old.returncode == 0 and old.stdout != raw:
                    if path.startswith("catalog/artifacts/"):
                        previous, incoming = json.loads(old.stdout), json.loads(raw)
                        if previous["sha256"] != incoming["sha256"]:
                            raise ValueError("Concurrent artifact identity conflict")
                        origins = previous.get("origins", [])
                        origins += [item for item in incoming.get("origins", []) if item not in origins]
                        incoming["origins"] = origins
                        for field in ("qualification", "previous_attempts", "failure", "reproduced_sha256"):
                            if field in previous:
                                incoming[field] = previous[field]
                        for field in ("build_check", "functional"):
                            if field in previous:
                                incoming[field] = previous[field]
                        raw = (json.dumps(incoming, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
                        (release.ROOT / path).write_bytes(raw)
                    elif not path.startswith("catalog/imports/"):
                        raise ValueError("Concurrent source path has different immutable bytes: " + path)
                blob = git("hash-object", "-w", "--stdin", data=raw).stdout.decode().strip()
                mode = "100755" if (release.ROOT / path).stat().st_mode & 0o111 else "100644"
                git("update-index", "--add", "--cacheinfo", mode, blob, path, env=index_env)
            tree = git("write-tree", env=index_env).stdout.decode().strip()
        if tree == git("rev-parse", parent + "^{tree}").stdout.decode().strip():
            return parent
        commit = git("commit-tree", tree, "-p", parent, env=env,
                     data=(message + "\n").encode()).stdout.decode().strip()
        if git("push", "origin", commit + ":refs/heads/main", check=False).returncode == 0:
            return commit
    raise RuntimeError("main advanced repeatedly; the frozen source files remain recoverable")


def index_publication(output, tag):
    receipt = (output / "publication.json").read_bytes()
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for _ in range(5):
        git("fetch", "--no-tags", "origin", "main")
        git("reset", "--hard", "FETCH_HEAD")
        path = release.ROOT / "catalog/releases" / (tag + ".json")
        if path.exists() and path.read_bytes() != receipt:
            raise ValueError("A different publication receipt already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(receipt)
        release.merge_manifest()
        git("add", "--", path.relative_to(release.ROOT).as_posix(), "manifest.json")
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return git("rev-parse", "HEAD").stdout.decode().strip()
        git("commit", "-m", "Index statically reviewed delivery " + tag)
        if git("push", "origin", "HEAD:refs/heads/main", check=False).returncode == 0:
            return git("rev-parse", "HEAD").stdout.decode().strip()
    raise RuntimeError("Publication succeeded but its index needs an FF retry")


def import_and_publish(archive, item, scratch):
    tag = release.validate_tag(item["tag"])
    receipt = {"schema_version": 1, "archive": item["file_name"],
               "sha256": item["sha256"], "bytes": item["bytes"], "review_policy": "static-trust-v1",
               "packages": [], "online_recipes": [], "errors": [], "status": "inspected"}
    assets = scratch / "delivered-artifacts"
    assets.mkdir()
    extracted = scratch / "member"
    extracted.mkdir()
    files, admitted = [], []
    existing_rows, _ = release.published_rows()
    existing_hashes = {row["sha256"] for row in existing_rows.values()}
    for number, (path, member) in enumerate(members(archive, item["members"], extracted), 1):
        origin = {"archive": item["file_name"], "sha256": item["sha256"], "bytes": item["bytes"],
                  "member": member.get("member")}
        checksum = member["sha256"]
        if checksum in existing_hashes:
            receipt["packages"].append({"sha256": checksum, "status": "already_published"})
            continue
        try:
            if member["method"] == "online-recipe":
                from online_recipe import import_recipe
                record = import_recipe(path, release.ROOT, origin)
            else:
                import_archives.import_package(path, release.ROOT, origin, static_trust=True)
                record = json.loads((release.ROOT / "catalog/artifacts" / (checksum + ".json")).read_text())
        except (ValueError, KeyError, TypeError) as error:
            # A malformed member cannot prevent other independent deliveries from
            # being retained and published. Outer and per-member byte locks above
            # remain mandatory and still fail the request on any mismatch.
            receipt["errors"].append({"sha256": checksum, "id": member["id"],
                                      "method": member["method"], "error_type": type(error).__name__,
                                      "error": str(error)[:600]})
            continue
        if any(record.get(key) != member[key] for key in ("id", "version", "method", "sha256", "bytes")):
            raise ValueError("Artifact identity differs from the explicit member plan")
        if "canonical_primary_index" in member:
            record["index_role"] = "canonical" if member["canonical_primary_index"] else "dependency-variant"
            record["origin_profile"] = member.get("origin_role", {})
        record_path = "catalog/artifacts/" + checksum + ".json"
        import_archives.write_json(release.ROOT / record_path, record)
        files.append(record_path)
        template = release.ROOT / import_archives.safe_relative(record["template"])
        files.extend(p.relative_to(release.ROOT).as_posix() for p in template.rglob("*") if p.is_file())
        summary = {key: record.get(key) for key in ("id", "version", "build", "method", "sha256", "release_eligible")}
        (receipt["online_recipes"] if record["method"] == "online-recipe" else receipt["packages"]).append(summary)
        if record["release_eligible"]:
            release.checked_record(checksum)
            os.link(path, assets / checksum)
            admitted.append(checksum)
        else:
            receipt["errors"].append({"sha256": checksum, "errors": record.get("qualification_errors", [])})
        if number % 25 == 0:
            print(json.dumps({"delivery": item["id"], "statically_reviewed": number,
                              "admitted": len(admitted)}), flush=True)
    if receipt["errors"]:
        receipt["status"] = "inspected_with_corrections_needed"
    receipt_path = "catalog/imports/" + item["sha256"] + ".json"
    import_archives.write_json(release.ROOT / receipt_path, receipt)
    files.append(receipt_path)
    if admitted:
        if len(admitted) > 950:
            raise ValueError("Explicit input exceeds one release's artifact limit; split its request")
        plan_path = "release-plans/" + tag + ".json"
        plan = {"schema_version": 1, "kind": "cpg_workload_release_plan", "tag": tag,
                "repository": release.REPOSITORY, "artifacts": admitted}
        prior = release.ROOT / plan_path
        if prior.exists() and json.loads(prior.read_text()) != plan:
            raise ValueError("An existing release plan has different artifacts")
        import_archives.write_json(prior, plan)
        files.append(plan_path)
    source_commit = commit_files(files, "Import statically reviewed workload delivery " + tag)
    # All generated source paths are now durable. Drop only this runner's transport checkout.
    git("reset", "--hard", source_commit)
    print(json.dumps({"delivery": item["id"], "source_commit": source_commit,
                      "admitted_artifacts": len(admitted), "corrections_needed": len(receipt["errors"])}), flush=True)
    if admitted:
        os.environ["CPG_DELIVERED_ARTIFACTS"] = str(assets)
        output = scratch / "release"
        release.publish(tag, output, source_commit=source_commit)
        indexed = index_publication(output, tag)
        print(json.dumps({"delivery": item["id"], "publication_index_commit": indexed,
                          "artifacts": len(admitted), "url": f"https://github.com/{release.REPOSITORY}/releases/tag/{tag}"}), flush=True)
    shutil.rmtree(assets)
    archive.unlink(missing_ok=True)


def main():
    request = json.loads((release.ROOT / ".transfer/request.json").read_text())
    branch = os.environ.get("GITHUB_REF_NAME", "")
    git("fetch", "--no-tags", "origin", "main")
    if git("merge-base", "--is-ancestor", request["source_commit"], "FETCH_HEAD", check=False).returncode:
        raise ValueError("Transfer's source commit is not in canonical main history")
    with tempfile.TemporaryDirectory(prefix="cpg-delivery-", dir=os.environ["RUNNER_TEMP"]) as folder:
        scratch = Path(folder)
        # A private repository reader arrives inside the authenticated CMS body.
        # It is pinned by every original source file and remains in RUNNER_TEMP.
        reader = scratch / "format-reader"
        paths = receive(request, branch, scratch, reader_destination=reader)
        import sys
        sys.path.insert(0, str(reader / "src"))
        for number, (path, item) in enumerate(zip(paths, request["inputs"])):
            current = scratch / ("batch-" + str(number))
            current.mkdir()
            import_and_publish(path, item, current)
    git("push", "origin", "--delete", branch)
    print(json.dumps({"deleted_transport_branch": branch}), flush=True)


if __name__ == "__main__":
    main()
