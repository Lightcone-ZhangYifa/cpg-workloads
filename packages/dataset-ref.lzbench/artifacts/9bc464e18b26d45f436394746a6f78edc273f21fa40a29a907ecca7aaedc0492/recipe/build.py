#!/usr/bin/env python3
"""Build the complete pinned upstream lzbench C/C++ profile from a separate copy.

Original CPG source material stays immutable. No network or package-manager
transactions. Rust/Zig optional codecs are unavailable in the recorded profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def source_inventory(root: Path) -> dict[str, dict]:
    result = {}
    for item in root.rglob('*'):
        if item.is_file() and not item.is_symlink():
            relative = item.relative_to(root).as_posix()
            result[relative] = {'bytes': item.stat().st_size, 'sha256': digest(item)}
        elif item.is_symlink():
            result[item.relative_to(root).as_posix()] = {'symlink_target': os.readlink(item)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        raise ValueError('1 <= jobs <= 4 for this bounded host profile')
    source = args.source.resolve(strict=True)
    build = args.build.resolve()
    prefix = args.prefix.resolve()
    assert source.is_dir() and (source / 'Makefile').is_file()
    assert not any(p in source.parents or p == source for p in (build, prefix))
    build.mkdir(parents=True, exist_ok=True)
    (prefix / 'bin').mkdir(parents=True, exist_ok=True)
    source_before = source_inventory(source)
    if len(source_before) < 5000:
        raise RuntimeError(f'Expected complete original lzbench archive, got only {len(source_before)} members')
    # Important: upstream Makefile writes misc/rust-codecs/target/lzbench-config
    # into SOURCE_PATH even when build runs out-of-tree.
    copy = build / 'upstream-build-copy'
    shutil.copytree(source, copy, symlinks=True)
    log = build / 'logs'
    log.mkdir(exist_ok=False)
    commands = []

    def run(label, argv, *, cwd=None, timeout=1800, env=None):
        started = time.monotonic()
        command = [str(x) for x in argv]
        with (log / f'{label}.stdout').open('wb') as stdout, (log / f'{label}.stderr').open('wb') as stderr:
            completed = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr, env=env,
                                       timeout=timeout, check=False, close_fds=True)
        commands.append({'label': label, 'argv': command, 'returncode': completed.returncode,
                         'duration_seconds': round(time.monotonic() - started, 5)})
        write_json(log / 'command-receipts.json', commands)
        if completed.returncode:
            raise RuntimeError(f'{label} failed with code {completed.returncode}; see {log}')

    environment = dict(os.environ)
    environment.pop('RUST_FEATURES', None)
    environment.update(LC_ALL='C', PYTHONDONTWRITEBYTECODE='1')
    # Disabling the unintended inherited RUST_FEATURES is essential on hosts
    # whose shell uses that name for unrelated product features.
    run('build', ['make', '-C', copy, '-j' + str(args.jobs), 'RUST_FEATURES=',
                  'RUST_TARGET_CPU=x86-64', 'CC=gcc', 'CXX=g++'], timeout=1800, env=environment)
    binary = copy / 'lzbench'
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError('Native lzbench ELF executable was not produced')
    shutil.copy2(binary, prefix / 'bin' / 'lzbench')
    (prefix / 'bin' / 'lzbench').chmod(0o755)
    notices = []
    for item in source.rglob('*'):
        if item.is_symlink() or not item.is_file():
            continue
        if not any(word in item.name.lower() for word in ('license', 'copyright', 'copying', 'notice')):
            continue
        rel = item.relative_to(source)
        destination = prefix / 'share' / 'licenses' / 'lzbench' / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        notices.append({'path': rel.as_posix(), 'sha256': digest(item)})
    if not any(x['path'] == 'LICENSE' for x in notices):
        raise RuntimeError('Original project root LICENSE was not retained')
    source_after = source_inventory(source)
    if source_before != source_after:
        difference = sorted(set(source_before) ^ set(source_after))
        raise RuntimeError('Build modified the original source directory: ' + repr(difference[:10]))
    write_json(prefix / 'share' / 'compiler-playground' / 'lzbench-native-profile.json', {
        'schema_version': 1,
        'original_source_revision': '2cc81a8ebccc0f43d4b7b7ff27847e5d39f96da9',
        'original_archive_sha256': '1a89a5d5a07af2f5a809a0d37585c4258de173e8b0b261b0c9883741e8e01a6f',
        'source_items': len(source_before),
        'source_unmodified': True,
        'build_profile': 'native-C-C++ full upstream default available on Debian 13 host; Rust and Zig optional codecs skipped by upstream',
        'make_flags': ['RUST_FEATURES=', 'RUST_TARGET_CPU=x86-64', 'CC=gcc', 'CXX=g++'],
        'binary_sha256': digest(prefix / 'bin' / 'lzbench'),
        'license_notice_count': len(notices),
        'redistribution_license_review_required': True,
        'official_benchmark_qualified': False,
        'ubuntu_24_native_qualified': False,
        'oci_qualified': False,
        'hardware_qualified': False,
    })
    print(json.dumps({'status': 'passed', 'source_unmodified': True, 'members': len(source_before),
                      'notices': len(notices), 'binary_sha256': digest(prefix / 'bin' / 'lzbench')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
