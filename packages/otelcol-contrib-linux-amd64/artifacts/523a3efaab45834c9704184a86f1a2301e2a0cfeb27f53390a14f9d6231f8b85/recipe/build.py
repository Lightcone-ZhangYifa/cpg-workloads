#!/usr/bin/env python3
"""Install the exact upstream Collector release without rebuilding Go sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

VERSION = "0.163.1"
ARCHIVE_SHA256 = "e93e6fd2b59427420a9e8eba5b9e78260df6d21e95283a7298084d2aa07f9df7"
ARCHIVE_BYTES = 115292512


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def install(archive, prefix):
    archive, prefix = Path(archive), Path(prefix)
    if archive.is_symlink() or archive.stat().st_size != ARCHIVE_BYTES or digest(archive) != ARCHIVE_SHA256:
        raise ValueError("The Collector archive differs from its existing exact input lock")
    release = prefix / "share/otelcol-contrib/release"
    release.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as stream:
        members, names = stream.getmembers(), set()
        for item in members:
            path = PurePosixPath(item.name)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.name
                    or path.as_posix() in names or not (item.isfile() or item.isdir())):
                raise ValueError("The Collector release contains an unsafe or duplicate entry")
            names.add(path.as_posix())
        binaries = [item for item in members if PurePosixPath(item.name).as_posix() == "otelcol-contrib"]
        if len(binaries) != 1 or not binaries[0].isfile():
            raise ValueError("The Collector release requires one regular root executable")
        for item in members:
            target = release / item.name
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(item.mode & 0o777)
    binary = release / "otelcol-contrib"
    if not binary.stat().st_mode & 0o111:
        raise ValueError("The original Collector executable lacks executable permission")
    (prefix / "bin").mkdir(exist_ok=True)
    (prefix / "bin/otelcol-contrib").symlink_to("../share/otelcol-contrib/release/otelcol-contrib")
    helpers = prefix / "share/compiler-playground/otelcol-contrib-linux-amd64"
    helpers.mkdir(parents=True)
    shutil.copy2(Path(__file__).with_name("check.py"), helpers / "check.py")
    files = [{"path": p.relative_to(release).as_posix(), "bytes": p.stat().st_size,
              "sha256": digest(p), "mode": p.stat().st_mode & 0o777}
             for p in sorted(release.rglob("*")) if p.is_file()]
    profile = {"schema_version": 1, "resource_id": "otelcol-contrib-linux-amd64",
               "version": VERSION, "scope": "Exact upstream precompiled Linux amd64 release; not a source rebuild",
               "archive_sha256": ARCHIVE_SHA256, "archive_bytes": ARCHIVE_BYTES,
               "binary_sha256": digest(binary), "upstream_files": files}
    (prefix / "share/otelcol-contrib/profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    print(json.dumps({"status": "passed", "version": VERSION, "upstream_files": len(files),
                      "binary_sha256": profile["binary_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--prefix", required=True, type=Path)
    args = parser.parse_args()
    install(args.source, args.prefix)
