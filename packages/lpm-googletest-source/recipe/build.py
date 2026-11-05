#!/usr/bin/env python3
"""Build a locked XML/testing library without modifying its original source."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'prefix'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, required=True)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    resource = config['id']
    evidence = args.prefix / 'share/compiler-playground' / resource
    evidence.mkdir(parents=True)
    cmake = Path(os.environ.get('CPG_CMAKE', '/usr/bin/cmake')).resolve()
    ninja = Path(os.environ.get('CPG_NINJA', '/usr/bin/ninja')).resolve()
    ctest = cmake.with_name('ctest')
    commands = []

    def run(label, argv, *, cwd=None):
        command = [str(value) for value in argv]
        print(json.dumps({'label': label, 'argv': command}), flush=True)
        with (evidence/(label+'.stdout')).open('wb') as out, (evidence/(label+'.stderr')).open('wb') as err:
            completed = subprocess.run(command, cwd=cwd, stdout=out, stderr=err)
        commands.append({'label': label, 'argv': command, 'returncode': completed.returncode})
        (evidence/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        if completed.returncode:
            raise RuntimeError('Upstream build/test failed: '+label)
        return (evidence/(label+'.stdout')).read_text(errors='replace')

    # Python upstream tests create bytecode caches beside test utilities.
    # Execute the unchanged project from a separate build copy so all original
    # material files remain byte-exact and no generated cache is transported.
    build_source = args.build/'upstream-build-copy'
    shutil.copytree(args.source, build_source, symlinks=True)
    source = build_source / config['source_subdir']
    listed = []
    tests = []
    for kind in ('static', 'shared'):
        build = args.build/kind
        shared = kind == 'shared'
        flags = config['cmake_options'] + [('-DEXPAT_SHARED_LIBS=' if resource == 'lpm-libexpat-source' else '-DBUILD_SHARED_LIBS=') + ('ON' if shared else 'OFF')]
        for option in config['test_options']:
            flags.append('-D'+option+'='+('OFF' if shared else 'ON'))
        run(kind+'-configure', [cmake, '-S', source, '-B', build, '-G', 'Ninja',
            '-DCMAKE_MAKE_PROGRAM='+str(ninja), '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER=/usr/bin/gcc', '-DCMAKE_CXX_COMPILER=/usr/bin/g++',
            '-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic',
            '-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic',
            '-DCMAKE_INSTALL_PREFIX='+str(args.prefix), '-DCMAKE_INSTALL_LIBDIR=lib',
            '-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON', '-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib',
            '-DPython3_EXECUTABLE=/usr/bin/python3', '-DPYTHON_EXECUTABLE=/usr/bin/python3', *flags])
        run(kind+'-build', [cmake, '--build', build, '--parallel', args.jobs])
        if not shared:
            listed = json.loads(run('ctest-list', [ctest, '--test-dir', build, '--show-only=json-v1']))['tests']
            if len(listed) < config['minimum_ctest_count']:
                raise RuntimeError('Upstream configured test list is unexpectedly small')
            run('ctest', [ctest, '--test-dir', build, '--output-on-failure', '--parallel', '1',
                         '--timeout', '180', '--output-junit', evidence/'upstream-tests.xml'])
            root = ET.parse(evidence/'upstream-tests.xml').getroot()
            cases = root.findall('.//testcase')
            if sorted(t['name'] for t in listed) != sorted(c.attrib['name'] for c in cases):
                raise RuntimeError('CTest did not execute the exact complete configured list')
            if any(c.find('failure') is not None or c.find('error') is not None or c.find('skipped') is not None for c in cases):
                raise RuntimeError('An upstream CTest was failed or skipped')
            target = args.prefix/'libexec'/resource
            target.mkdir(parents=True)
            for name in config['installed_tests']:
                matches = [p for p in build.rglob(name) if p.is_file() and p.read_bytes()[:4] == b'\x7fELF']
                if len(matches) != 1:
                    raise RuntimeError('Expected one actual upstream test executable: '+name)
                shutil.copy2(matches[0], target/name)
                tests.append(name)
        run(kind+'-install', [cmake, '--install', build])
    # Upstream pkg-config files sometimes contain expanded absolute libdirs.
    # Keep the original tree untouched and make only installed metadata relative.
    for path in (args.prefix/'lib/pkgconfig').glob('*.pc'):
        content = path.read_text()
        # GoogleTest 1.15 emits absolute libdir/includedir without a prefix
        # variable. Require that precise upstream shape before relativizing it.
        lines = content.splitlines()
        expected_lib = 'libdir='+str(args.prefix/'lib')
        expected_include = 'includedir='+str(args.prefix/'include')
        if (lines.count(expected_lib) != 1 or lines.count(expected_include) != 1
                or any(line.startswith('prefix=') for line in lines)
                or content.count(str(args.prefix)) != 2):
            raise RuntimeError('Unrecognized upstream pkg-config directories: '+path.name)
        content = 'prefix=${pcfiledir}/../..\n'+content.replace(str(args.prefix), '${prefix}')
        path.write_text(content)
    shutil.copytree(args.source, args.prefix/'share'/resource/'source', symlinks=True)
    for name in ('build.py', 'check.py', 'config.json', config['consumer']):
        shutil.copy2(Path(__file__).with_name(name), evidence/name)
    profile = {'schema_version': 1, 'id': resource, 'version': config['version'],
        'source_modified': False, 'libraries': ['static', 'shared'],
        'source_ctest_passed': len(listed), 'source_ctest_names': [t['name'] for t in listed],
        'installed_tests': tests, 'cmake_options': config['cmake_options'],
        'unperformed': config['unperformed'], 'pkgconfig_prefix': '${pcfiledir}/../..'}
    (evidence/'profile.json').write_text(json.dumps(profile, indent=2)+'\n')


if __name__ == '__main__':
    main()
