#!/usr/bin/env python3
"""Recreate complete exact oneDNN Git material using the existing CPG APIs.

The pinned codeload archive and one pinned Git blob remain immutable inputs.
Only the declared codeload CRLF transformation is reversed in an independent
material copy. No oneDNN code is built, imported, or executed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

from compiler_playground.resource_deploy import acquire_file, unpack_archive
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.archive import inventory
from compiler_playground.packages.spec import validate_spec


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def exact(path, lock):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != lock['bytes'] or sha(path) != lock['sha256']:
        raise ValueError('Original fixed input identity mismatch: ' + lock['id'])


def acquire(lock, cache, *, no_network, license_class, receipt):
    item = {'id': lock['id'], 'source_url': lock['url'], 'sha256': lock['sha256'],
            'archive_bytes': lock['bytes'], 'license_class': license_class}
    if no_network:
        item['bundled_path'] = str(cache / 'sha256' / lock['sha256'][:2] / lock['sha256'])
    return acquire_file(item, cache, receipt=receipt)


def assemble(raw, locks, cache, payload):
    exact(raw, locks['resolved_main_source'])
    if payload.exists():
        raise ValueError('Material output must be a fresh independent directory')
    unpack_archive(raw, payload, strip_root=True)
    seen = set()
    with tarfile.open(raw) as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or '\\' in member.name:
                raise ValueError('Unsafe original source member')
            if name.parts[0] != 'oneDNN-' + locks['source_commit']:
                raise ValueError('Unexpected source archive root')
            parts = name.parts[1:]
            if not parts:
                if not member.isdir():
                    raise ValueError('Original archive root must be a directory')
                continue
            relative = '/'.join(parts)
            if relative in seen:
                raise ValueError('Duplicate source member')
            seen.add(relative)
            if not (member.isfile() or member.isdir()) or member.mode not in (0o664, 0o775):
                raise ValueError('Unreviewed original source mode or type')
            target = payload.joinpath(*parts)
            if target.is_symlink() or not target.resolve().is_relative_to(payload.resolve()):
                raise ValueError('Source extraction is not an ordinary contained copy')
            target.chmod(member.mode)
    corrections = locks['exact_git_blob_replacements']
    if len(corrections) != 1 or corrections[0]['path'] != 'cmake/template.vcxproj.user':
        raise ValueError('Only the reviewed original oneDNN CRLF transformation is supported')
    correction = corrections[0]
    target = payload / correction['path']
    original = target.read_bytes()
    if len(original) != correction['archive_bytes'] or hashlib.sha256(original).hexdigest() != correction['archive_sha256']:
        raise ValueError('Original codeload CRLF bytes changed')
    blob_lock = locks['additional_acquisition_locks'][0]
    if blob_lock['id'] != correction['input_id'] or len(locks['additional_acquisition_locks']) != 1:
        raise ValueError('Original Git blob acquisition identity changed')
    blob = cache / 'sha256' / blob_lock['sha256'][:2] / blob_lock['sha256']
    exact(blob, blob_lock)
    raw_blob = blob.read_bytes()
    git_sha = hashlib.sha1(b'blob ' + str(len(raw_blob)).encode() + b'\0' + raw_blob).hexdigest()
    if git_sha != correction['git_blob_sha1'] or raw_blob.replace(b'\n', b'\r\n') != original:
        raise ValueError('Git blob is not the exact original preimage of the declared CRLF transformation')
    mode = target.stat().st_mode & 0o777
    shutil.copyfile(blob, target)
    target.chmod(mode)
    if target.stat().st_nlink != 1 or (target.stat().st_dev, target.stat().st_ino) == (blob.stat().st_dev, blob.stat().st_ino):
        raise ValueError('Generated material must be an independent ordinary copy')
    rows = inventory(payload)
    for row in rows:
        if row['kind'] == 'file' and row['bytes'] <= 1024:
            if (payload / row['path']).read_bytes().startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                raise ValueError('Unresolved Git LFS pointer')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition', type=Path, default=Path(__file__).resolve().parents[1] / 'package.json')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    root, cache = args.definition.resolve().parent, args.cache.resolve()
    spec = validate_spec(json.loads(args.definition.read_text()))
    locks = json.loads((root / 'recipe/acquisition-locks.json').read_text())
    if spec['id'] != 'dataset-ref.onednn' or spec['sources'] != locks['original_sources'] or locks['lfs_objects']:
        raise ValueError('Canonical oneDNN source identity changed')
    main_lock = locks['resolved_main_source']
    for key, value in spec['sources'][0].items():
        if not (key in ('sha256', 'bytes') and value is None) and main_lock[key] != value:
            raise ValueError('Acquisition lock changed an original discovery fact')
    receipts = []
    for lock in [main_lock] + locks['additional_acquisition_locks']:
        receipt = {}
        acquire(lock, cache, no_network=args.no_network,
                license_class=spec['metadata']['catalog']['license_class'], receipt=receipt)
        receipts.append(receipt)
    raw = cache / 'sha256' / main_lock['sha256'][:2] / main_lock['sha256']
    with tempfile.TemporaryDirectory(prefix='cpg-onednn-fixed-material-') as temporary:
        payload = Path(temporary) / 'payload'
        rows = assemble(raw, locks, cache, payload)
        expected = json.loads((root / 'recipe/material-manifest.json').read_text())
        if rows != expected['files']:
            raise ValueError('Complete prepared inventory differs from the frozen original Git closure')
        result = pack(spec, args.output, method='material', payload=payload, recipe_dir=root / 'recipe',
            provenance={'original_source_lock': main_lock, 'original_sources_unchanged': True,
                'exact_git_tree_sha1': locks['exact_git_tree_sha1'],
                'exact_git_blob_replacements': locks['exact_git_blob_replacements'],
                'execution_category': 'expanded_exact_git_tree_material_with_declared_codeload_crlf_normalization',
                'qualification_scope': spec['recipe']['qualification_scope'],
                'original_raw_inputs_retained_unchanged': True,
                'native_execution_qualified': False, 'dataset_api_qualified': False})
    verify_package(args.output, expected_sha256=result['sha256'], expected_bytes=result['bytes'])
    print(json.dumps({'status': 'passed', 'resource_id': spec['id'], 'artifact': result,
                      'acquisitions': receipts}, indent=2))


if __name__ == '__main__':
    main()
