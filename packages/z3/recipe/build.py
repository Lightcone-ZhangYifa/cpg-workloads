#!/usr/bin/env python3
"""Build the immutable Z3 tree and execute a declared upstream unit-test subset."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'prefix'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 6:
        raise RuntimeError('This build-4 profile permits at most six compiler jobs')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    actual = (args.source/'scripts/VERSION.txt').read_text().strip()
    if actual != config['source_version']:
        raise RuntimeError('Immutable source version differs from its profile')
    evidence = args.prefix/'share/compiler-playground/z3'
    evidence.mkdir(parents=True)
    cmake = Path(os.environ.get('CPG_CMAKE', '/usr/bin/cmake')).resolve()
    ninja = Path(os.environ.get('CPG_NINJA', '/usr/bin/ninja')).resolve()
    commands = []

    def run(label, argv, *, timeout=2400):
        command = [str(x) for x in argv]
        print(json.dumps({'label': label, 'argv': command}), flush=True)
        with (evidence/(label+'.stdout')).open('wb') as stdout, (evidence/(label+'.stderr')).open('wb') as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout)
        commands.append({'label': label, 'argv': command, 'returncode': result.returncode,
                         'stdout': label+'.stdout', 'stderr': label+'.stderr'})
        (evidence/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        if result.returncode:
            raise RuntimeError('Upstream build/test command failed: '+label)
        return (evidence/(label+'.stdout')).read_text(errors='replace')

    build = args.build/'z3'
    run('configure', [cmake, '-S', args.source, '-B', build, '-G', 'Ninja',
        '-DCMAKE_MAKE_PROGRAM='+str(ninja), '-DCMAKE_BUILD_TYPE=Debug',
        '-DCMAKE_CXX_FLAGS_DEBUG=-O0 -g0', '-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic',
        '-DCMAKE_CXX_COMPILER=/usr/bin/g++', '-DCMAKE_INSTALL_PREFIX='+str(args.prefix),
        '-DCMAKE_INSTALL_LIBDIR=lib', '-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON',
        '-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib', '-DBUILD_SHARED_LIBS=ON',
        '-DPython3_EXECUTABLE=/usr/bin/python3', '-DZ3_ENABLE_EXAMPLE_TARGETS=OFF',
        '-DZ3_BUILD_TEST_EXECUTABLES=ON', '-DZ3_BUILD_PYTHON_BINDINGS=OFF'])
    run('build', [cmake, '--build', build, '--target', 'z3', 'libz3', 'test-z3', '--parallel', args.jobs], timeout=5400)
    tests = [p for p in build.rglob('test-z3') if p.is_file() and not p.is_symlink()]
    if len(tests) != 1:
        raise RuntimeError('Expected exactly one actually built upstream test executable')
    executable = tests[0]
    listed = run('upstream-list', [executable, '/h'], timeout=60)
    names = [line.strip() for line in listed.splitlines() if line.startswith('    ')]
    if len(names) < 100 or not set(config['upstream_groups']) <= set(names):
        raise RuntimeError('Selected groups are absent from the actual upstream test registry')
    if re.findall(r'^PASS\s*$', run('upstream-empty-selector-negative', [executable, '/seq', 'cpg_nonexistent_group'], timeout=30), re.M):
        raise RuntimeError('An unknown test selector unexpectedly ran a test')
    passed = []
    for name in config['upstream_groups']:
        stdout = run('upstream-'+name, [executable, '/seq', name], timeout=300)
        if len(re.findall(r'^PASS\s*$', stdout, re.M)) != 1:
            raise RuntimeError('Upstream test did not execute and report exactly one group: '+name)
        passed.append(name)
    run('install', [cmake, '--install', build], timeout=180)
    # Preserve the complete original material tree without generated files.
    shutil.copytree(args.source, args.prefix/'share/z3/source', symlinks=True)
    for name in ('build.py', 'check.py', 'config.json', 'consumer.cpp'):
        shutil.copy2(Path(__file__).with_name(name), evidence/name)
    profile = {'schema_version': 1, 'id': 'z3', 'version': config['version'],
        'source_version': actual, 'source_modified': False,
        'configuration': 'Shared library and CLI; generic x86-64; Debug assertions enabled; -O0 -g0',
        'build_budget': {'compiler_timeout_seconds': 5400, 'maximum_jobs': 6, 'actual_jobs': args.jobs, 'build_cache': 'fresh operation; no reused objects'},
        'source_bytecode_generation': 'PYTHONDONTWRITEBYTECODE=1',
        'upstream_tests': {'registry_groups': names, 'passed_groups': passed,
            'group_count': len(passed), 'test_executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'empty_selector_negative_control': 'zero PASS markers detected and excluded',
            'assertion_count': 'not_reported_by_upstream',
            'scope': 'Named upstream groups executed at source-build time; installed checks use fresh API and CLI consumers'},
        'unperformed': config['unperformed']}
    (evidence/'profile.json').write_text(json.dumps(profile, indent=2)+'\n')


if __name__ == '__main__':
    main()
