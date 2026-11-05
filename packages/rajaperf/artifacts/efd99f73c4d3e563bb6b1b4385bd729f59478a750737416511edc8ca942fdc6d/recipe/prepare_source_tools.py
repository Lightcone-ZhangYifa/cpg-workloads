#!/usr/bin/env python3
"""Prepare precisely locked fixed Gitlinks and build-support archives for source tools.

Uses the existing CPG acquire_file API. No install, Git checkout, or implicit
revision substitution occurs here. The active recipe contains only this code,
the fixed lock, and license/input identity evidence, never these raw archives.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    rows = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Artifact-only source inputs cannot contain symlinks')
        row = {'path': path.relative_to(root).as_posix(), 'mode': stat.S_IMODE(path.stat().st_mode)}
        if path.is_file():
            row.update(kind='file', bytes=path.stat().st_size, sha256=sha(path))
        elif path.is_dir():
            row.update(kind='directory')
        else:
            raise ValueError('Artifact-only source inputs cannot contain special files')
        rows.append(row)
    return sorted(rows, key=lambda row: row['path'])


def expected_inventory(lock):
    rows = [dict(row) for row in lock['directories']]
    rows.extend({key: row[key] for key in ('path', 'kind', 'mode', 'bytes', 'sha256')}
                for row in lock['artifacts'])
    return sorted(rows, key=lambda row: row['path'])


def verify_tools(root, lock):
    if not root.is_dir() or root.is_symlink() or stat.S_IMODE(root.stat().st_mode) != lock['tools_root_mode']:
        raise ValueError('Artifact-only source tools root differs from its lock')
    if inventory(root) != expected_inventory(lock):
        raise ValueError('Artifact-only source tools are missing, changed, or contain undeclared entries')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lock', type=Path, default=Path(__file__).with_name('source-artifacts.json'))
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--framework-path', type=Path)
    p.add_argument('--no-network', action='store_true')
    a = p.parse_args()
    if a.framework_path:
        sys.path.insert(0, str(a.framework_path / 'src'))
    sys.dont_write_bytecode = True
    from compiler_playground.resource_deploy import acquire_file
    lock = json.loads(a.lock.read_text())
    if lock.get('schema_version') != 1 or a.output.exists():
        raise ValueError('Use a supported explicit input lock and a fresh output')
    a.output.mkdir(parents=True)
    a.output.chmod(lock['tools_root_mode'])
    receipts = []
    for row in lock['directories']:
        path = PurePosixPath(row['path'])
        if path.is_absolute() or '..' in path.parts or path.as_posix() != row['path']:
            raise ValueError('Unsafe declared tool directory')
        target = a.output / path
        target.mkdir(parents=True, exist_ok=False)
        target.chmod(row['mode'])
    for row in lock['artifacts']:
        path = PurePosixPath(row['path'])
        if path.is_absolute() or '..' in path.parts or path.as_posix() != row['path']:
            raise ValueError('Unsafe declared tool archive')
        item = {'id': row['input_id'], 'source_url': row['url'], 'sha256': row['sha256'],
                'archive_bytes': row['bytes'], 'license_class': 'open'}
        if a.no_network:
            item['bundled_path'] = str(a.cache.resolve() / 'sha256' / row['sha256'][:2] / row['sha256'])
        receipt = {}
        raw = acquire_file(item, a.cache, receipt=receipt)
        target = a.output / path
        shutil.copy2(raw, target)
        target.chmod(row['mode'])
        if sha(target) != row['sha256'] or target.stat().st_size != row['bytes'] or target.stat().st_ino == raw.stat().st_ino:
            raise ValueError('Prepared source-tool archive is not an independent exact ordinary file')
        receipts.append({'lock': row, 'acquisition': receipt})
    verify_tools(a.output, lock)
    print(json.dumps({'status': 'passed', 'tools': str(a.output), 'lock_sha256': sha(a.lock),
                      'no_network': a.no_network, 'acquisitions': receipts,
                      'inventory': inventory(a.output)}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
