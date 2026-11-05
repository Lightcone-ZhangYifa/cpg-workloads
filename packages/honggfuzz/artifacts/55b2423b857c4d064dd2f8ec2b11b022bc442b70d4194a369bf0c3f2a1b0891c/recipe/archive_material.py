#!/usr/bin/env python3
"""Keep an exact upstream tar and an inspectable deterministic member inventory.

The material view is deliberately an archive container. Link targets remain
unchanged inside the locked tar; they are never materialized by this helper.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

ARCHIVE_NAME = 'honggfuzz-source.tar.gz'
MEMBERS_NAME = 'archive-members.json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def manifest(raw, lock):
    raw = Path(raw)
    need(raw.is_file() and not raw.is_symlink(), 'Expected an ordinary upstream source archive')
    need(raw.stat().st_size == lock['bytes'] and sha(raw) == lock['sha256'], 'Original source archive lock mismatch')
    rows, names = [], set()
    with tarfile.open(raw, 'r:*') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            need(not path.is_absolute() and '..' not in path.parts and path.parts, 'Unsafe original member name')
            need(member.name not in names, 'Duplicate original archive member name')
            names.add(member.name)
            row = {'path': member.name, 'mode': member.mode & 0o7777,
                   'uid': member.uid, 'gid': member.gid, 'mtime': member.mtime,
                   'uname': member.uname, 'gname': member.gname}
            if member.isfile():
                with archive.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                row.update(kind='file', bytes=member.size, sha256=digest)
            elif member.isdir():
                row['kind'] = 'directory'
            elif member.issym() or member.islnk():
                row.update(kind='symlink' if member.issym() else 'hardlink', target=member.linkname)
            else:
                raise RuntimeError('Unsupported original source member kind: ' + member.name)
            if member.pax_headers:
                row['pax_headers'] = member.pax_headers
            rows.append(row)
    value = {'schema_version': 1, 'kind': 'compiler-playground-original-archive-material',
             'resource_id': lock['id'], 'representation': 'exact-archive-with-member-inventory',
             'archive': {'path': ARCHIVE_NAME, 'sha256': lock['sha256'], 'bytes': lock['bytes']},
             'original_source_lock': lock,
             'link_handling': 'Original link targets are recorded and remain unmodified inside the archive; no extraction is performed for this material view.',
             'members': sorted(rows, key=lambda row: row['path'])}
    return value


def serialize(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode('utf-8')


def create(raw, destination, lock):
    destination = Path(destination)
    need(not destination.exists(), 'Refuse to overwrite an existing material directory')
    value = manifest(raw, lock)
    destination.mkdir(parents=True)
    shutil.copyfile(raw, destination / ARCHIVE_NAME)
    (destination / ARCHIVE_NAME).chmod(0o444)
    (destination / MEMBERS_NAME).write_bytes(serialize(value))
    (destination / MEMBERS_NAME).chmod(0o644)
    need(sha(destination / ARCHIVE_NAME) == lock['sha256'], 'The retained archive copy changed')
    return value


def verify(destination, lock):
    destination = Path(destination)
    need({p.name for p in destination.iterdir()} == {ARCHIVE_NAME, MEMBERS_NAME}, 'Unexpected archive material members')
    for name in (ARCHIVE_NAME, MEMBERS_NAME):
        need((destination / name).is_file() and not (destination / name).is_symlink(), 'Material member is not an ordinary file')
    value = manifest(destination / ARCHIVE_NAME, lock)
    need((destination / MEMBERS_NAME).read_bytes() == serialize(value), 'Original archive member inventory differs')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--source-lock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.source_lock.read_text())
    value = create(args.raw, args.output, lock)
    print(json.dumps({'status': 'passed', 'representation': value['representation'],
                      'archive_sha256': lock['sha256'], 'members': len(value['members'])}, sort_keys=True))


if __name__ == '__main__':
    main()
