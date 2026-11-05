"""Keep locked external recipe inputs in artifacts, outside the source tree.

Original ordinary .deb/.whl files under recipe/ or tools/ qualify. Exact
recipe/inputs/<sha256> files additionally require an inventory-bound authored
JSON HTTPS source lock. Ordinary recipe/<source-basename>.tar.gz files also
require an exact original HTTPS lock whose URL basename agrees. Each mapping
binds the original CPG archive, manifest and complete inventory row.
Public source URLs are reused only from hash-verified original JSON metadata.
No package manager, compiler, check script or delivered executable is invoked.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile
from urllib.parse import urlparse


DESCRIPTOR = "authored-inputs.json"
CHECKSUM = re.compile(r"[a-f0-9]{64}")
JSON_LIMIT = 1024 * 1024


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _ordinary(path, root):
    return (not path.is_symlink() and path.is_file()
            and path.resolve().is_relative_to(root.resolve()))


def _inventory(manifest):
    rows = {row["path"]: row for row in manifest["files"]}
    if len(rows) != len(manifest["files"]):
        raise ValueError("External authored inputs require a unique original inventory")
    return rows


def _hash_named_input(name):
    parts = PurePosixPath(name).parts
    return (len(parts) == 3 and parts[:2] == ("recipe", "inputs")
            and CHECKSUM.fullmatch(parts[2]) is not None)


def _named_source_archive(name):
    parts = PurePosixPath(name).parts
    return (len(parts) == 2 and parts[0] == "recipe"
            and parts[1].endswith(".tar.gz"))


def _inputs(manifest):
    result = {}
    for name, row in _inventory(manifest).items():
        relative = PurePosixPath(name)
        if (not relative.parts or relative.parts[0] not in {"recipe", "tools"}
                or (relative.suffix.lower() not in {".deb", ".whl"}
                    and not _hash_named_input(name) and not _named_source_archive(name))):
            continue
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or relative.as_posix() != name or any(ord(c) < 32 for c in name)
                or row.get("kind") != "file" or type(row.get("bytes")) is not int
                or not 0 < row["bytes"] <= 2 * 1024**3
                or not isinstance(row.get("sha256"), str)
                or CHECKSUM.fullmatch(row["sha256"]) is None
                or type(row.get("mode")) is not int or not 0 <= row["mode"] <= 0o777):
            raise ValueError("Finished authored input has no safe complete original inventory")
        if _hash_named_input(name) and relative.name != row["sha256"]:
            raise ValueError("Hash-named authored input differs from its original content identity")
        result[name] = row
    return result


def _public_url(value):
    if not isinstance(value, str):
        return False
    url = urlparse(value)
    return (url.scheme == "https" and bool(url.netloc) and not url.username
            and not url.password and not url.query and not url.fragment)


def _walk(value, pointer=""):
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from _walk(child, pointer + "/" + escaped)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, pointer + "/" + str(index))


def _locks(manifest, template):
    """Index exact public source locks; do not print or retain other JSON fields."""
    docs = [("manifest.json", {"manifest_sha256": manifest["manifest_sha256"]}, manifest)]
    for name, row in sorted(_inventory(manifest).items()):
        path = PurePosixPath(name)
        if (path.parts[0] not in {"recipe", "tools"} or path.suffix != ".json"
                or row.get("kind") != "file" or row.get("bytes", JSON_LIMIT + 1) > JSON_LIMIT):
            continue
        source = template / name
        if (not _ordinary(source, template) or source.stat().st_size != row["bytes"]
                or _sha(source) != row["sha256"]):
            raise ValueError("Original authored input metadata differs from inventory: " + name)
        try:
            value = json.loads(source.read_bytes())
        except (ValueError, UnicodeError):
            continue
        docs.append((name, {"sha256": row["sha256"], "bytes": row["bytes"]}, value))
    result = {}
    for name, identity, value in docs:
        for pointer, row in _walk(value):
            checksum = row.get("sha256")
            size = row.get("bytes", row.get("size", row.get("size_bytes")))
            url = row.get("url", row.get("source_url"))
            if (isinstance(checksum, str) and CHECKSUM.fullmatch(checksum)
                    and type(size) is int and size > 0 and _public_url(url)):
                result.setdefault((checksum, size), []).append({
                    "kind": "https", "url": url,
                    "document": {"path": name, **identity}, "json_pointer": pointer})
    return result


def descriptor_for(record, manifest, template):
    rows = _inputs(manifest)
    if not rows:
        return None
    if (not isinstance(record.get("sha256"), str) or CHECKSUM.fullmatch(record["sha256"]) is None
            or type(record.get("bytes")) is not int or not 0 < record["bytes"] <= 2 * 1024**3
            or record.get("manifest_sha256") != manifest.get("manifest_sha256")
            or not isinstance(manifest.get("manifest_sha256"), str)
            or CHECKSUM.fullmatch(manifest["manifest_sha256"]) is None
            or record.get("method") != manifest.get("method")
            or record.get("id") != manifest.get("package", {}).get("id")):
        raise ValueError("External authored inputs lack their exact original package identity")
    locks = _locks(manifest, Path(template))
    members = {}
    for name, row in sorted(rows.items()):
        candidates = locks.get((row["sha256"], row["bytes"]), [])
        if _hash_named_input(name):
            # These source archives need the independently inventory-bound
            # original supplemental JSON, never the CPG fallback or an unbound URL.
            candidates = [source for source in candidates
                          if source["document"]["path"] != "manifest.json"]
            if not candidates:
                raise ValueError("Hash-named authored input has no exact original HTTPS supplemental lock")
        if _named_source_archive(name):
            candidates = [source for source in candidates
                          if PurePosixPath(urlparse(source["url"]).path).name
                          == PurePosixPath(name).name]
            if not candidates:
                raise ValueError("Source archive input has no matching original HTTPS basename lock")
        source = candidates[0] if candidates else {
            "kind": "original_cpg_member", "artifact_sha256": record["sha256"],
            "artifact_bytes": record["bytes"], "member": name}
        members[name] = {"inventory": row, "source": source}
    return {"schema_version": 2, "kind": "cpg_external_authored_inputs",
            "artifact_sha256": record["sha256"], "artifact_bytes": record["bytes"],
            "manifest_sha256": manifest["manifest_sha256"], "members": members}


def review_for(descriptor):
    return {"status": "passed", "source_type": "exact_original_recipe_inputs",
            "artifact_sha256": descriptor["artifact_sha256"],
            "manifest_sha256": descriptor["manifest_sha256"],
            "descriptor_sha256": hashlib.sha256(_encoded(descriptor)).hexdigest(),
            "runtime_execution": "not_performed"}


def _verify_descriptor(record, manifest, template, descriptor):
    expected = descriptor_for(record, manifest, template)
    if expected is None:
        raise ValueError("Unexpected external authored-input descriptor")
    if descriptor.get("schema_version") == 2:
        if descriptor != expected:
            raise ValueError("External authored-input mapping differs from its exact original locks")
    elif descriptor.get("schema_version") == 1:
        # Read the previously published two-input descriptor without widening it.
        rows, locks = _inputs(manifest), _locks(manifest, template)
        config = descriptor.get("configuration", {})
        config_row = _inventory(manifest).get(config.get("path"), {})
        if (set(descriptor) != {"schema_version", "kind", "artifact_sha256", "manifest_sha256", "configuration", "members"}
                or descriptor.get("kind") != expected["kind"]
                or descriptor.get("artifact_sha256") != record["sha256"]
                or descriptor.get("manifest_sha256") != manifest["manifest_sha256"]
                or set(descriptor.get("members", {})) != set(rows)
                or config_row.get("kind") != "file"
                or any(config.get(key) != config_row.get(key) for key in ("bytes", "sha256"))):
            raise ValueError("Legacy authored-input mapping differs from its original inventory")
        for name, item in descriptor["members"].items():
            row = rows[name]
            candidates = locks.get((row["sha256"], row["bytes"]), [])
            if (any(item.get(key) != row[key] for key in ("sha256", "bytes", "mode"))
                    or not any(source["url"] == item.get("url")
                               and source["document"]["path"] == config["path"] for source in candidates)):
                raise ValueError("Legacy authored input differs from its original public source lock")
    else:
        raise ValueError("Unknown external authored-input descriptor format")
    return expected["members"]


def verify_authored_inputs(record, manifest, template):
    template = Path(template)
    path = template / DESCRIPTOR
    review = record.get("authored_inputs_review")
    if review is None and not path.exists() and not path.is_symlink():
        return {}
    if not _ordinary(path, template) or path.stat().st_size > JSON_LIMIT:
        raise ValueError("Missing or unsafe external authored-input descriptor")
    descriptor = json.loads(path.read_bytes())
    members = _verify_descriptor(record, manifest, template, descriptor)
    if path.read_bytes() != _encoded(descriptor) or review != review_for(descriptor):
        raise ValueError("External authored-input descriptor differs from its recorded review")
    for name in members:
        target = template / name
        if target.exists() or target.is_symlink():
            raise ValueError("Finished build dependency must remain outside the source checkout: " + name)
    return members


def externalize_authored_inputs(record, manifest, template):
    """After original CPG verification, retain its locks and discard only copies."""
    template = Path(template)
    descriptor = descriptor_for(record, manifest, template)
    if descriptor is None:
        return {}
    existing = []
    for name, item in descriptor["members"].items():
        path, row = template / name, item["inventory"]
        if path.exists() or path.is_symlink():
            if (not _ordinary(path, template) or path.stat().st_size != row["bytes"]
                    or _sha(path) != row["sha256"]):
                raise ValueError("Imported build dependency differs from its original byte identity")
            existing.append(path)
    target = template / DESCRIPTOR
    if target.exists() or target.is_symlink():
        if not _ordinary(target, template):
            raise ValueError("Unsafe existing authored-input descriptor")
        _verify_descriptor(record, manifest, template, json.loads(target.read_bytes()))
    target.write_bytes(_encoded(descriptor))
    record["authored_inputs_review"] = review_for(descriptor)
    for path in existing:
        path.unlink()
    return verify_authored_inputs(record, manifest, template)


def acquire_authored_inputs(record, manifest, template, cache, *, network):
    """Hydrate exact input bytes into scratch; never install or execute them."""
    from release import published_rows, published_variants, source_file
    members = verify_authored_inputs(record, manifest, template)
    result, original = {}, None
    cache = Path(cache)
    for name, item in members.items():
        row, source = item["inventory"], item["source"]
        if source["kind"] == "https":
            result[name] = source_file({"url": source["url"], "sha256": row["sha256"],
                                        "bytes": row["bytes"]}, cache, network=network)
            continue
        if original is None:
            delivered = os.environ.get("CPG_DELIVERED_ARTIFACTS")
            candidate = Path(delivered) / record["sha256"] if delivered else cache / record["sha256"]
            if candidate.exists() or candidate.is_symlink():
                if (candidate.is_symlink() or not candidate.is_file()
                        or candidate.stat().st_size != record["bytes"] or _sha(candidate) != record["sha256"]):
                    raise ValueError("Original CPG input differs from its complete byte identity")
                original = candidate
            else:
                public, _ = published_rows()
                matches = [x for x in list(public.values()) + published_variants()
                           if x.get("sha256") == record["sha256"] and x.get("bytes") == record["bytes"]]
                if not matches:
                    raise FileNotFoundError("Exact original CPG is not in the supplied cache or publication receipts")
                original = source_file({"url": matches[0]["download_url"], "sha256": record["sha256"],
                                        "bytes": record["bytes"]}, cache, network=network)
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / row["sha256"]
        if target.exists() or target.is_symlink():
            result[name] = source_file(row, cache, network=False)
            continue
        with tempfile.NamedTemporaryFile(prefix=row["sha256"] + ".", suffix=".part", dir=cache, delete=False) as output:
            temporary = Path(output.name)
        try:
            with tarfile.open(original, "r:gz") as archive:
                selected = [entry for entry in archive if entry.name == name]
                if len(selected) != 1 or not selected[0].isfile() or selected[0].size != row["bytes"]:
                    raise ValueError("Original CPG has no unique ordinary locked input member")
                count = 0
                with archive.extractfile(selected[0]) as stream, temporary.open("wb") as output:
                    while block := stream.read(1024 * 1024):
                        count += len(block)
                        if count > row["bytes"]:
                            raise ValueError("Original CPG input exceeds its locked size")
                        output.write(block)
            if count != row["bytes"] or _sha(temporary) != row["sha256"]:
                raise ValueError("Original CPG member differs from its complete inventory lock")
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            result[name] = source_file(row, cache, network=False)
        finally:
            temporary.unlink(missing_ok=True)
    return result

