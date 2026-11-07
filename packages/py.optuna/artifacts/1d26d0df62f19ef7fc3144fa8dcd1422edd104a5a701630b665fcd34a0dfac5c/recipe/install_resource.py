#!/usr/bin/env python3
"""A resource recipe invoked by the unchanged CPG PackageManager."""
from __future__ import annotations
import argparse
import email
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
import tarfile
import hashlib

from profile_inputs import Profile


def run(argv, *, cwd, env):
    print(json.dumps({'argv': [str(x) for x in argv], 'cwd': str(cwd)}), flush=True)
    subprocess.run([str(x) for x in argv], cwd=cwd, env=env, check=True)


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def constraints(directory, requirements, output):
    versions = {}
    preferred = {}
    for req in requirements:
        if '==' in req:
            key, value = req.split('==', 1)
            preferred[normalized(key.split('[')[0])] = value
    for file in directory.glob('*.whl'):
            with zipfile.ZipFile(file) as wheel:
                entries = [n for n in wheel.namelist() if n.endswith('.dist-info/METADATA')]
                if len(entries) != 1:
                    raise ValueError('Ambiguous wheel distribution metadata')
                meta = email.message_from_bytes(wheel.read(entries[0]))
            versions.setdefault(normalized(meta['Name']), set()).add(meta['Version'])
    rows = []
    for name, values in sorted(versions.items()):
        if name in preferred:
            if preferred[name] not in values:
                raise ValueError('Requested distribution version is absent: ' + name)
            value = preferred[name]
        elif len(values) == 1:
            value = next(iter(values))
        else:
            raise ValueError('Pin the ambiguous private wheel versions explicitly: ' + name)
        rows.append(name + '==' + value)
    output.write_text('\n'.join(rows) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('resource', 'source', 'prefix', 'assets', 'build'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    recipe = Path(__file__).resolve().parent
    profile = Profile(args.assets, recipe)
    definition = profile.definition
    if definition['id'] != args.resource:
        raise ValueError('Execution profile resource identity differs')
    prefix, build, source = Path(args.prefix), Path(args.build), Path(args.source)
    temporary = build / 'tmp'
    temporary.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update(PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_CONFIG_FILE=os.devnull,
               PIP_NO_CACHE_DIR='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', TMPDIR=str(temporary),
               USE_BUNDLED_LIBUV='1', MAKEFLAGS='-j1')
    env.pop('PYTHONPATH', None)
    if definition.get('mode') == 'R':
        if (recipe / 'R-Makevars').is_file():
            env['R_MAKEVARS_USER'] = str(recipe / 'R-Makevars')
        if definition.get('cmake_wheel'):
            cmake = build / 'cmake-runtime'
            cmake.mkdir()
            with zipfile.ZipFile(profile.path(definition['cmake_wheel'])) as archive:
                for name in archive.namelist():
                    path = Path(name)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('Unsafe CMake wheel member')
                archive.extractall(cmake)
                for member in archive.infolist():
                    mode = (member.external_attr >> 16) & 0o777
                    target = cmake / member.filename
                    if mode and target.is_file():
                        target.chmod(mode)
            env['PATH'] = str(cmake / 'cmake/data/bin') + os.pathsep + env.get('PATH', '')
        root = prefix / 'R-root'
        root.mkdir()
        run(['dpkg-deb', '-x', profile.path(definition['R_binary_input']), root], cwd=build, env=env)
        library = prefix / 'R-library'
        library.mkdir()
        driver = recipe / 'src/r_driver.py'
        run([sys.executable, '-S', driver, '--r-root', root, '--r-lib', library, '--configure'], cwd=build, env=env)
        for name in definition['R_source_inputs']:
            run([sys.executable, '-S', driver, '--r-root', root, '--r-lib', library,
                 '--', 'CMD', 'INSTALL', '--no-test-load', '-l', library, profile.path(name)], cwd=build, env=env)
        source_copy = build / 'source-copy'
        shutil.copytree(source, source_copy)
        run([sys.executable, '-S', driver, '--r-root', root, '--r-lib', library,
             '--', 'CMD', 'INSTALL', '--no-test-load', '-l', library, source_copy], cwd=build, env=env)
    else:
        directories = definition['wheel_directories']
        verified = profile.validate_directories(directories)
        requirements = definition['requirements']
        lock = build / 'constraints.txt'
        staged = profile.stage(directories, build / 'offline-inputs')
        constraints(staged, requirements + definition.get('build_requirements', []), lock)
        run([sys.executable, '-S', '-m', 'venv', '--copies', prefix], cwd=build, env=env)
        python = prefix / 'bin/python'
        command = [python, '-I', '-m', 'pip', 'install', '--no-index', '--no-cache-dir', '--no-compile',
                   '--disable-pip-version-check', '--no-build-isolation', '--constraint', lock]
        command += ['--find-links', staged]
        run(command + definition.get('build_requirements', ['setuptools', 'wheel']), cwd=build, env=env)
        run(command + requirements, cwd=build, env=env)
        for index, auxiliary in enumerate(definition.get('auxiliary_sources', [])):
            entry = {'path': auxiliary} if isinstance(auxiliary, str) else auxiliary
            path = profile.path(entry['path'])
            if entry.get('patch'):
                expanded = build / ('auxiliary-' + str(index))
                expanded.mkdir()
                with tarfile.open(path) as archive:
                    archive.extractall(expanded, filter='data')
                roots = list(expanded.iterdir())
                if len(roots) != 1 or not roots[0].is_dir():
                    raise ValueError('Expected one root in auxiliary source archive')
                path = roots[0]
                patch = entry['patch']
                affected = path / patch['file']
                if hashlib.file_digest(affected.open('rb'), 'sha256').hexdigest() != patch['before_sha256']:
                    raise ValueError('Auxiliary source before-patch SHA256 differs')
                original = affected.read_text()
                if original.count(patch['old']) != 1:
                    raise ValueError('Compatibility patch does not match exactly once')
                affected.write_text(original.replace(patch['old'], patch['new']))
                if hashlib.file_digest(affected.open('rb'), 'sha256').hexdigest() != patch['after_sha256']:
                    raise ValueError('Auxiliary source after-patch SHA256 differs')
            run(command + ['--no-deps', path], cwd=build, env=env)
        if definition.get('install_original_source', True):
            source_copy = build / 'source-copy'
            if source.is_dir():
                shutil.copytree(source, source_copy)
            else:
                source_copy.mkdir()
                shutil.copy2(source, source_copy / source.name)
                source_copy = source_copy / source.name
            run(command + ['--no-deps', '--force-reinstall', source_copy], cwd=build, env=env)
        run([python, '-I', '-m', 'pip', 'check'], cwd=build, env=env)
        print(json.dumps({'verified_execution_input_files': verified}))
    (build / 'recipe-install-result.json').write_text(json.dumps({
        'status': 'installed', 'resource': args.resource, 'source': str(source),
        'prefix': str(prefix), 'execution_profile_manifest_sha256': profile.contract['manifest_sha256'],
        'network_policy': 'pip no-index, no cache and closed local wheel inputs; no implicit downloads',
        'scope': definition.get('scope', 'Bounded compiler-parameter tuning demonstration')}, indent=2) + '\n')
    print('CPG_WORKER083_INSTALL_COMPLETE')


if __name__ == '__main__':
    main()
