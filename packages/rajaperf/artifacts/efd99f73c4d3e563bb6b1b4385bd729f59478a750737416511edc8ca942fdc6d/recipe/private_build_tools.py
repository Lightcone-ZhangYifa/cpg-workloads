#!/usr/bin/env python3
"""Independently unpack exact, complete build-only support inputs per operation.

These are precompiled CMake/Ninja inputs, not source-build or APT qualifications.
No package database, LD override, shared installed prefix or network is used.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def tree(root):
    rows, inodes = [], set()
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'Build tool tree contains a link')
        row = {'path': path.relative_to(root).as_posix(), 'mode': stat.S_IMODE(info.st_mode)}
        if stat.S_ISREG(info.st_mode):
            require(info.st_nlink == 1 and (info.st_dev, info.st_ino) not in inodes,
                    'Build tool files are not ordinary independent copies')
            inodes.add((info.st_dev, info.st_ino))
            row.update(kind='file', bytes=info.st_size, sha256=sha(path))
        else:
            require(stat.S_ISDIR(info.st_mode), 'Build tool tree contains a special file')
            row.update(kind='directory')
        rows.append(row)
    rows.sort(key=lambda row: row['path'])
    return rows


def extract_complete(archive, destination, layout):
    require(not destination.exists(), 'Private build tool destination already exists')
    destination.mkdir(parents=True)
    with tarfile.open(archive) as source:
        members = source.getmembers()
        require(sum(m.isfile() for m in members) == layout['regular_files']
                and sum(m.isdir() for m in members) == layout['directories']
                and sum(m.size for m in members if m.isfile()) == layout['ordinary_bytes'],
                'Complete build-tool archive layout differs')
        expected, names = [], set()
        for member in members:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in member.name,
                    'Build-tool archive path escapes its root')
            require(member.isfile() or member.isdir(), 'Build-tool archive contains a link or special file')
            name = path.as_posix()
            require(name not in names, 'Build-tool archive has a duplicate path')
            names.add(name)
            if name == '.':
                require(member.isdir(), 'Archive root is not a directory')
                continue
            row = {'path': name, 'mode': member.mode}
            if member.isfile():
                with source.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                row.update(kind='file', bytes=member.size, sha256=digest)
            else:
                row.update(kind='directory')
            expected.append(row)
        # Some original tarballs omit required ancestor directory records.  The
        # lock names exactly those derived ancestors; no arbitrary extra path
        # is admitted and no original member or source byte is altered.
        implicit = {parent.as_posix()
                    for row in expected for parent in PurePosixPath(row['path']).parents
                    if parent.as_posix() != '.' and parent.as_posix() not in names}
        locked_implicit = layout['implicit_directories']
        require(len(locked_implicit) == len(implicit)
                and {row['path'] for row in locked_implicit} == implicit
                and all(row == {'path': row['path'], 'mode': 0o755}
                        for row in locked_implicit),
                'Implicit build-tool ancestor directories differ from the explicit lock')
        for row in sorted(locked_implicit, key=lambda item: (len(PurePosixPath(item['path']).parts), item['path'])):
            path = destination / row['path']
            path.mkdir(mode=row['mode'])
            path.chmod(row['mode'])
            expected.append({'path': row['path'], 'kind': 'directory', 'mode': row['mode']})
        source.extractall(destination, filter='data')
    expected.sort(key=lambda row: row['path'])
    require(tree(destination) == expected, 'Complete private tool copy differs from its source archive')
    return expected


def prepare(raw_tools, lock, recipe, build, logs):
    require(lock['schema_version'] == 1 and len(lock['artifacts']) == 2,
            'Unsupported private build-tool lock')
    require(not any(key.startswith('LD_') for key in os.environ),
            'Private build tools require a clean runtime environment without LD overrides')
    root = build / 'private-build-tools'
    require(not root.exists() and root.resolve(strict=False) == root,
            'Private build-tool root is not fresh and canonical')
    root.mkdir()
    evidence = {'status': 'running', 'scope': lock['scope'], 'root': str(root),
                'host_package_transactions': 0, 'resource_or_apt_qualification_increment': 0,
                'inputs': [], 'trees': [], 'commands': []}
    executables = {}
    for item in lock['artifacts']:
        raw = raw_tools / item['path']
        require(raw.is_file() and not raw.is_symlink() and raw.stat().st_nlink == 1
                and raw.stat().st_size == item['bytes'] and sha(raw) == item['sha256'],
                'Declared private build-tool input is missing or changed')
        if item['format'] == 'tar.gz':
            notice = item['official_checksum']
            checksum = recipe / notice['recipe_file']
            require(checksum.stat().st_size == notice['bytes'] and sha(checksum) == notice['sha256'],
                    'Official CMake checksum evidence differs')
            matches = [line.split() for line in checksum.read_text().splitlines()
                       if line.endswith(Path(item['path']).name)]
            require(matches == [[item['sha256'], Path(item['path']).name]],
                    'Official checksum does not bind the selected CMake binary bundle')
            destination = root / 'cmake'
            rows = extract_complete(raw, destination, item['archive_layout'])
            cmake_root = destination / item['archive_layout']['root']
            executables.update(cmake=cmake_root / 'bin/cmake', ctest=cmake_root / 'bin/ctest')
        elif item['format'] == 'deb':
            destination = root / 'ninja'
            data_tar = root / 'ninja-original-filesystem.tar'
            argv = ['dpkg-deb', '--fsys-tarfile', str(raw)]
            with data_tar.open('xb') as stream:
                result = subprocess.run(argv, stdout=stream, stderr=subprocess.PIPE, check=False)
            require(result.returncode == 0, 'Cannot read the exact Ninja DEB filesystem')
            rows = extract_complete(data_tar, destination, item['archive_layout'])
            executables['ninja'] = destination / 'usr/bin/ninja'
            evidence['commands'].append({'argv': argv, 'returncode': result.returncode,
                                         'stderr': result.stderr.decode(errors='replace'),
                                         'filesystem_tar_sha256': sha(data_tar),
                                         'filesystem_tar_bytes': data_tar.stat().st_size})
        else:
            raise ValueError('Unsupported private build-tool archive format')
        for license_row in item['license_evidence']:
            license_path = destination / license_row['archive_member']
            require(license_path.is_file() and license_path.stat().st_size == license_row['bytes']
                    and sha(license_path) == license_row['sha256'], 'Original build-tool license differs')
        evidence['inputs'].append(item)
        evidence['trees'].append({'root': str(destination), 'files': rows,
                                  'ordinary_file_count': sum(row['kind'] == 'file' for row in rows)})
    expected_versions = {'cmake': 'cmake version 3.28.3', 'ctest': 'ctest version 3.28.3', 'ninja': '1.11.1'}
    for name, path in executables.items():
        commands = [([str(path), '--version'], 'version'), (['ldd', str(path)], 'runtime'),
                    (['readelf', '-h', '-d', str(path)], 'ELF')]
        for argv, kind in commands:
            completed = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
            evidence['commands'].append({'tool': name, 'kind': kind, 'argv': argv,
                                         'returncode': completed.returncode,
                                         'stdout': completed.stdout, 'stderr': completed.stderr})
            require(completed.returncode == 0, 'Private build tool observation failed: ' + name + ' ' + kind)
            if kind == 'version':
                require(completed.stdout.splitlines()[0] == expected_versions[name], 'Private tool version differs')
            elif kind == 'runtime':
                require('not found' not in completed.stdout + completed.stderr, 'Private build tool runtime is missing')
            else:
                require('Advanced Micro Devices X86-64' in completed.stdout, 'Private tool ELF architecture differs')
    evidence.update(status='passed', executables={name: {'path': str(path), 'sha256': sha(path),
                    'bytes': path.stat().st_size} for name, path in executables.items()})
    write(logs / 'private-build-tools.json', evidence)
    return {name: str(path) for name, path in executables.items()}, evidence


def verify_after_use(evidence, logs):
    for entry in evidence['trees']:
        require(tree(Path(entry['root'])) == entry['files'], 'Private build tools changed during the source build')
    write(logs / 'private-build-tools-after-build.json', {
        'status': 'passed', 'unchanged_full_tool_trees': [entry['root'] for entry in evidence['trees']],
        'ordinary_files': sum(entry['ordinary_file_count'] for entry in evidence['trees']),
        'shared_tool_installation_prefixes': False, 'LD_overrides': False,
        'resource_or_apt_qualification_increment': 0})
