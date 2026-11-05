#!/usr/bin/env python3
"""Statically import and publish one explicitly requested, encrypted delivery batch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import random
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
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


def merge_import_receipt(previous, incoming):
    """Merge independent inspections of one exact archive against current main."""
    if any(previous.get(key) != incoming.get(key) for key in ("sha256", "bytes")):
        raise ValueError("Concurrent archive receipt has a different byte identity")
    value = {**previous, **incoming}
    attempted = {row.get("sha256") for key in ("packages", "online_recipes", "errors")
                 for row in incoming.get(key, []) if isinstance(row, dict) and row.get("sha256")}
    for key in ("packages", "online_recipes"):
        by_sha = {row["sha256"]: row for row in previous.get(key, [])}
        by_sha.update({row["sha256"]: row for row in incoming.get(key, [])})
        value[key] = [by_sha[key] for key in sorted(by_sha)]
    errors = [row for row in previous.get("errors", [])
              if not isinstance(row, dict) or row.get("sha256") not in attempted]
    for row in incoming.get("errors", []):
        if row not in errors:
            errors.append(row)
    value["errors"] = errors
    value["status"] = "inspected_with_corrections_needed" if errors else "inspected"
    for key in ("nonpackage_members", "excluded_members"):
        if key in previous or key in incoming:
            value[key] = max(previous.get(key, 0), incoming.get(key, 0))
    return value


def commit_files(paths, message):
    """Cache immutable blobs, then apply a small FF transaction to current main."""
    paths = sorted(set(paths))
    allowed = ("packages/", "catalog/artifacts/", "catalog/imports/", "release-plans/")
    prepared = {}
    for path in paths:
        import_archives.safe_relative(path)
        source = release.ROOT / path
        if (not path.startswith(allowed) or path == "packages/registry.json"
                or "\n" in path or "\r" in path or source.is_symlink() or not source.is_file()):
            raise ValueError("Unexpected file in source-only import commit")
        raw = source.read_bytes()
        blob = git("hash-object", "-w", "--stdin", data=raw).stdout.decode().strip()
        prepared[path] = (raw, blob, "100755" if source.stat().st_mode & 0o111 else "100644")
    env = dict(os.environ, GIT_AUTHOR_NAME="github-actions[bot]",
               GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
               GIT_COMMITTER_NAME="github-actions[bot]",
               GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
    failure = "main advanced throughout the bounded source-commit retries"
    commit = None
    for attempt in range(20):
        git("fetch", "--no-tags", "origin", "main")
        parent = git("rev-parse", "FETCH_HEAD").stdout.decode().strip()
        existing = {}
        for entry in git("ls-tree", "-r", "-z", parent).stdout.split(b"\0"):
            if entry:
                header, name = entry.split(b"\t", 1)
                mode, kind, blob = header.decode().split()
                existing[name.decode()] = (mode, kind, blob)
        updates = []
        for path in paths:
            raw, blob, mode = prepared[path]
            old = existing.get(path)
            if old == (mode, "blob", blob):
                continue
            if old is not None and (old[1] != "blob" or old[0] == "120000"):
                raise ValueError("Concurrent source path is not an ordinary file")
            if old is not None and old[2] != blob:
                previous_raw = git("cat-file", "blob", old[2]).stdout
                if path.startswith("catalog/artifacts/"):
                    previous, incoming = json.loads(previous_raw), json.loads(raw)
                    if any(previous.get(key) != incoming.get(key) for key in (
                            "sha256", "bytes", "id", "version", "build", "method",
                            "target", "manifest_sha256", "template")):
                        raise ValueError("Concurrent artifact identity conflict")
                    origins = list(previous.get("origins", []))
                    origins += [item for item in incoming.get("origins", []) if item not in origins]
                    incoming["origins"] = origins
                    for field in ("qualification", "previous_attempts", "failure", "blocker",
                                  "reproduced_sha256", "build_check", "functional"):
                        if field in previous:
                            incoming[field] = previous[field]
                    raw = (json.dumps(incoming, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
                elif path.startswith("catalog/imports/"):
                    value = merge_import_receipt(json.loads(previous_raw), json.loads(raw))
                    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
                else:
                    raise ValueError("Concurrent source path has different immutable bytes: " + path)
                blob = git("hash-object", "-w", "--stdin", data=raw).stdout.decode().strip()
            updates.append((mode + " " + blob + "\t" + path).encode() + b"\0")
        if not updates:
            return parent
        with tempfile.TemporaryDirectory(prefix="cpg-source-index-") as folder:
            index_env = dict(env, GIT_INDEX_FILE=str(Path(folder) / "index"))
            git("read-tree", parent, env=index_env)
            git("update-index", "-z", "--index-info", data=b"".join(updates), env=index_env)
            tree = git("write-tree", env=index_env).stdout.decode().strip()
        if tree == git("rev-parse", parent + "^{tree}").stdout.decode().strip():
            return parent
        commit = git("commit-tree", tree, "-p", parent, env=env,
                     data=(message + "\n").encode()).stdout.decode().strip()
        result = git("push", "origin", commit + ":refs/heads/main", check=False)
        if result.returncode == 0:
            return commit
        observed = git("ls-remote", "origin", "refs/heads/main", check=False)
        current = observed.stdout.decode().split()
        if current and current[0] == commit:
            return commit
        if observed.returncode == 0 and current and current[0] == parent:
            failure = "source push was rejected without a competing main update"
            if b"GH001" in result.stderr or b"exceeds GitHub" in result.stderr:
                failure = "source push rejected an oversized Git object"
            break
        print(json.dumps({"source_commit_retry": attempt + 1,
                          "reason": "main advanced during the FF transaction"}), flush=True)
        time.sleep(min(0.25 * (attempt + 1), 2.0) + random.random())
    if commit is not None:
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        if run_id.isdigit():
            checkpoint = "checkpoint/source-" + run_id + "-" + commit[:12]
            saved = git("push", "origin", commit + ":refs/heads/" + checkpoint, check=False).returncode == 0
            print(json.dumps({"source_checkpoint": checkpoint, "saved": saved,
                              "commit": commit}), flush=True)
    raise RuntimeError(failure)

def prepared_members(archive, item, scratch):
    """Optionally apply an exact reviewed metadata revision without executing it."""
    for path, member in members(archive, item["members"], scratch):
        revision_lock = member.get("revision")
        if revision_lock is None:
            yield path, member
            continue
        relative = import_archives.safe_relative(revision_lock["path"])
        if relative.parts[:2] != ("catalog", "revisions"):
            raise ValueError("A metadata revision must name its reviewed source record")
        revision_path = release.ROOT / relative
        if (revision_path.is_symlink() or not revision_path.is_file()
                or import_archives.sha256(revision_path) != revision_lock["sha256"]):
            raise ValueError("Reviewed metadata revision differs from its frozen identity")
        revision = release.load_json(revision_path)
        if revision["original_artifact"] != {"sha256": member["sha256"], "bytes": member["bytes"]}:
            raise ValueError("Metadata revision names a different original artifact")
        from repack_static_revision import repack
        corrected = revision["corrected"]
        result = scratch / (corrected["sha256"] + ".revision")
        repack(path, release.ROOT / import_archives.safe_relative(corrected["template"]), revision, result)
        revised = {**member, **{key: corrected[key] for key in ("sha256", "bytes")},
                   "original_artifact": revision["original_artifact"]}
        try:
            yield result, revised
        finally:
            result.unlink(missing_ok=True)


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
        git("add", "--all", "--", path.relative_to(release.ROOT).as_posix(), "manifest.json", "profiles")
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
    existing_hashes = {row["sha256"] for row in [*existing_rows.values(), *release.published_variants(), *release.published_recipes()]}
    for number, (path, member) in enumerate(prepared_members(archive, item, extracted), 1):
        origin = {"archive": item["file_name"], "sha256": item["sha256"], "bytes": item["bytes"],
                  "member": member.get("member")}
        if member.get("revision"):
            origin.update(metadata_revision=member["revision"], original_artifact=member["original_artifact"])
        checksum = member["sha256"]
        if checksum in existing_hashes:
            receipt["packages"].append({"sha256": checksum, "status": "already_published"})
            continue
        try:
            if member.get("method") == "online-recipe":
                from online_recipe import import_recipe
                record = import_recipe(path, release.ROOT, origin)
            else:
                import_archives.import_package(path, release.ROOT, origin, static_trust=True)
                record = json.loads((release.ROOT / "catalog/artifacts" / (checksum + ".json")).read_text())
        except (ValueError, KeyError, TypeError) as error:
            # A malformed member cannot prevent other independent deliveries from
            # being retained and published. Outer and per-member byte locks above
            # remain mandatory and still fail the request on any mismatch.
            receipt["errors"].append({"sha256": checksum, "id": member.get("id"),
                                      "method": member.get("method"), "error_type": type(error).__name__,
                                      "error": str(error)[:600]})
            continue
        if any(record.get(key) != member[key] for key in ("id", "version", "method", "sha256", "bytes")
               if key in member):
            raise ValueError("Artifact identity differs from the explicit member plan")
        if "canonical_primary_index" in member:
            record["index_role"] = "canonical" if member["canonical_primary_index"] else "dependency-variant"
            record["origin_profile"] = member.get("origin_role", {})
            record["dependency_profiles"] = member.get("original_dependency_profiles", [])
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
    for completed in request.get("completed_transports", []):
        name, expected = completed["branch"], completed["sha"]
        if (not re.fullmatch(r"transport/secure-[a-z0-9._-]+", name) or name == branch
                or release.COMMIT.fullmatch(expected) is None):
            raise ValueError("Invalid completed-transport cleanup request")
        actual = git("ls-remote", "origin", "refs/heads/" + name).stdout.decode().strip()
        if actual:
            if actual.split()[0] != expected:
                raise ValueError("Completed transport changed; preserve its branch")
            git("push", "origin", "--delete", name)
            print(json.dumps({"deleted_completed_transport": name}), flush=True)
    with tempfile.TemporaryDirectory(prefix="cpg-delivery-", dir=os.environ["RUNNER_TEMP"]) as folder:
        scratch = Path(folder)
        # A private repository reader arrives inside the authenticated CMS body.
        # It is pinned by every original source file and remains in RUNNER_TEMP.
        reader = scratch / "format-reader"
        paths = receive(request, branch, scratch, reader_destination=reader)
        import sys
        sys.path.insert(0, str(reader / "src"))
        if "assembly" in request:
            from delivery_archive import prepare
            assembled = prepare(paths, request["inputs"], request["assembly"], scratch)
            deliveries = [(assembled, request["assembly"]["delivery"])]
        else:
            deliveries = list(zip(paths, request["inputs"]))
        for number, (path, item) in enumerate(deliveries):
            current = scratch / ("batch-" + str(number))
            current.mkdir()
            import_and_publish(path, item, current)
            shutil.rmtree(current)
    git("push", "origin", "--delete", branch)
    print(json.dumps({"deleted_transport_branch": branch}), flush=True)


if __name__ == "__main__":
    main()
