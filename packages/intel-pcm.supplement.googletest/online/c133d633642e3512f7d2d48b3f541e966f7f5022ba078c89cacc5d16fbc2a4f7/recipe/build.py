#!/usr/bin/env python3
"""Build exact retained upstream sources and exercise a declared native profile."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identities(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink()}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'prefix'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, required=True)
    args = parser.parse_args()
    recipe = Path(__file__).parent
    config = json.loads((recipe / 'config.json').read_text())
    resource = config['id']
    logs = args.build / 'native-logs'
    logs.mkdir(parents=True)
    original = identities(args.source)
    assert original, 'Original source inventory is empty'
    source = args.build / 'upstream-build-copy'
    shutil.copytree(args.source, source, symlinks=True)
    tools = {name: shutil.which(name) for name in ('cmake', 'ctest', 'ninja', 'gcc', 'g++')}
    assert all(tools.values()), 'A declared host build command is unavailable'
    commands = []

    def run(label, argv, *, cwd=None, timeout=1200):
        command = list(map(str, argv))
        out, err = logs / (label + '.stdout'), logs / (label + '.stderr')
        started = time.monotonic()
        with out.open('wb') as stdout, err.open('wb') as stderr:
            completed = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                       timeout=timeout, check=False)
        commands.append({'label': label, 'argv': command, 'cwd': str(cwd) if cwd else None,
                         'returncode': completed.returncode, 'seconds': time.monotonic() - started,
                         'stdout': str(out), 'stdout_sha256': sha(out),
                         'stderr': str(err), 'stderr_sha256': sha(err)})
        write(logs / 'commands.json', commands)
        print(json.dumps({'label': label, 'returncode': completed.returncode}), flush=True)
        if completed.returncode != 0:
            raise RuntimeError(label + ' failed; retained logs: ' + str(logs))
        return out.read_text(errors='replace')

    upstream = None
    for kind in ('static', 'shared'):
        build = args.build / kind
        flags = ['-DBUILD_SHARED_LIBS=' + ('ON' if kind == 'shared' else 'OFF')]
        if config['family'] == 'googletest':
            flags += ['-DBUILD_GMOCK=ON', '-DINSTALL_GTEST=ON',
                      '-Dgtest_build_tests=' + ('ON' if kind == 'static' else 'OFF'),
                      '-Dgmock_build_tests=' + ('ON' if kind == 'static' else 'OFF'),
                      '-DPython3_EXECUTABLE=' + str(shutil.which('python3')),
                      '-DPYTHON_EXECUTABLE=' + str(shutil.which('python3'))]
        # simdjson's normal library configuration is used unchanged. Its optional
        # developer mode downloads additional datasets and benchmark projects;
        # that larger configuration is explicitly outside this selected profile.
        run(kind + '-configure', [tools['cmake'], '-S', source, '-B', build, '-G', 'Ninja',
            '-DCMAKE_MAKE_PROGRAM=' + tools['ninja'], '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER=' + tools['gcc'], '-DCMAKE_CXX_COMPILER=' + tools['g++'],
            '-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic',
            '-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic',
            '-DCMAKE_INSTALL_PREFIX=' + str(args.prefix), '-DCMAKE_INSTALL_LIBDIR=lib',
            '-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON', '-DCMAKE_INSTALL_RPATH=$ORIGIN', *flags])
        run(kind + '-build', [tools['cmake'], '--build', build, '--parallel', args.jobs])
        if config['family'] == 'googletest' and kind == 'static':
            listed = json.loads(run('ctest-list', [tools['ctest'], '--test-dir', build,
                                                  '--show-only=json-v1']))['tests']
            if len(listed) < 60:
                raise RuntimeError('Expected complete enabled GoogleTest/GoogleMock CTest list')
            junit = logs / 'upstream-tests.xml'
            run('ctest', [tools['ctest'], '--test-dir', build, '--output-on-failure',
                          '--parallel', args.jobs, '--timeout', '180', '--output-junit', junit])
            cases = ET.parse(junit).getroot().findall('.//testcase')
            if sorted(t['name'] for t in listed) != sorted(t.get('name') for t in cases):
                raise RuntimeError('CTest execution differs from its complete configured list')
            failures = sum(c.find('failure') is not None for c in cases)
            errors = sum(c.find('error') is not None for c in cases)
            skipped = sum(c.find('skipped') is not None for c in cases)
            if failures or errors or skipped:
                raise RuntimeError('CTest has failed, errored or skipped outer tests')
            upstream = {'status': 'passed', 'scope': 'Every CTest entry in enabled upstream static GoogleTest/GoogleMock configuration',
                        'listed': len(listed), 'executed': len(cases), 'failures': failures,
                        'errors': errors, 'skipped': skipped,
                        'test_names': [t['name'] for t in listed],
                        'count_unit': 'CTest entries; internal assertion/intentional-negative counts are not inferred'}
        run(kind + '-install', [tools['cmake'], '--install', build])

    relocation = []
    for path in sorted((args.prefix / 'lib/pkgconfig').glob('*.pc')):
        old = path.read_text()
        if str(args.prefix) not in old:
            raise RuntimeError('Unexpected upstream pkg-config shape: ' + path.name)
        new = old.replace(str(args.prefix), '${prefix}')
        if config['family'] == 'googletest':
            if any(line.startswith('prefix=') for line in old.splitlines()):
                raise RuntimeError('Unexpected GoogleTest prefix variable')
            new = 'prefix=${pcfiledir}/../..\n' + new
        else:
            if new.count('prefix=${prefix}') != 1:
                raise RuntimeError('Unexpected simdjson prefix variable')
            new = new.replace('prefix=${prefix}', 'prefix=${pcfiledir}/../..', 1)
        before = sha(path)
        path.write_text(new)
        relocation.append({'installed_file': path.relative_to(args.prefix).as_posix(),
                           'original_sha256': before, 'result_sha256': sha(path),
                           'change': 'Installed pkg-config metadata uses its own location; original source is unchanged'})
    write(logs / 'installed-metadata-relocation.json', relocation)

    (args.prefix / 'bin').mkdir(exist_ok=True)
    libraries = config['libraries']
    for kind in ('static', 'shared'):
        suffix = '.a' if kind == 'static' else '.so'
        executable = args.prefix / 'bin' / ('cpg-native-check' + ('' if kind == 'static' else '-shared'))
        run(kind + '-consumer-build', [tools['g++'], '-std=c++17', '-O2',
            '-march=x86-64', '-mtune=generic', '-I' + str(args.prefix / 'include'),
            recipe / 'consumer.cpp', *[args.prefix / 'lib' / ('lib' + n + suffix) for n in libraries],
            '-pthread', '-Wl,-rpath,$ORIGIN/../lib', '-o', executable])
        run(kind + '-consumer-run', [executable])

    if config['family'] == 'simdjson':
        selected = ['padded_string_tests', 'unicode_tests']
        target = args.prefix / 'libexec' / resource
        target.mkdir(parents=True)
        for name in selected:
            run(name + '-build', [tools['g++'], '-std=c++17', '-O2', '-march=x86-64', '-mtune=generic',
                '-I' + str(args.prefix / 'include'), source / 'tests' / (name + '.cpp'),
                args.prefix / 'lib/libsimdjson.a', '-pthread', '-o', target / name])
            run(name + '-run', [target / name])
        upstream = {'status': 'passed', 'scope': 'Two unchanged standalone upstream test programs; optional developer CTest/benchmark configuration not run',
                    'listed': len(selected), 'executed': len(selected), 'failures': 0,
                    'errors': 0, 'skipped': 0, 'test_names': selected,
                    'count_unit': 'upstream test programs, not individual assertions'}
    write(logs / 'upstream-summary.json', upstream)
    # Preserve all original files, documentation and notices, with no source edits.
    preserved = args.prefix / 'share' / resource / 'source'
    shutil.copytree(args.source, preserved, symlinks=True)
    after = identities(args.source)
    preserved_inventory = identities(preserved)
    changed = sorted(k for k in set(original) | set(after) if original.get(k) != after.get(k))
    if changed or preserved_inventory != original:
        raise RuntimeError('Original source or complete installed source copy changed')
    write(logs / 'original-source-check.json', {'original_files': len(original),
          'original_logical_bytes': sum((args.source / p).stat().st_size for p in original),
          'changed_original_files': changed, 'complete_preserved_source': True,
          'original_inventory': original})
    evidence = args.prefix / 'share/compiler-playground' / resource
    evidence.mkdir(parents=True)
    for name in ('build.py', 'check.py', 'consumer.cpp', 'config.json', 'original-package.json', 'resolved-sources.json'):
        shutil.copy2(recipe / name, evidence / name)
    write(evidence / 'profile.json', {'resource_id': resource, 'upstream_version': config['upstream_version'],
          'libraries': ['static', 'shared'], 'source_modified': False,
          'retained_source_files': len(original), 'upstream': upstream,
          'installed_metadata_relocations': relocation, 'unperformed': config['unperformed']})


if __name__ == '__main__':
    main()
