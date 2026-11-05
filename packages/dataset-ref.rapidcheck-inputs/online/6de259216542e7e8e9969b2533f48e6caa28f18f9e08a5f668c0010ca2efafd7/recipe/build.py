#!/usr/bin/env python3
"""Build RapidCheck with its fixed parent Gitlinks and every configured CTest."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from prepare_source_tools import verify_tools
from private_build_tools import prepare as prepare_private_build_tools, verify_after_use


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
    for name in ('source', 'build', 'prefix', 'tools'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, required=True)
    args = parser.parse_args()
    recipe = Path(__file__).parent
    config = json.loads((recipe / 'config.json').read_text())
    resource = config['id']
    logs = args.build / 'native-logs'
    logs.mkdir(parents=True)
    original_main = identities(args.source)
    source = args.build / 'complete-original-source'
    shutil.copytree(args.source, source, symlinks=True)
    tool_lock = json.loads((recipe / config['source_artifacts_lock']).read_text())
    gitlink_lock = json.loads((recipe / 'fixed-gitlink-artifacts.json').read_text())
    build_tools_lock = json.loads((recipe / config['build_tool_artifacts_lock']).read_text())
    if tool_lock['artifacts'] != gitlink_lock['artifacts'] + build_tools_lock['artifacts'] or tool_lock['directories'] != gitlink_lock['directories'] + build_tools_lock['directories']:
        raise ValueError('Source tools do not exactly equal the two declared fixed input locks')
    verify_tools(args.tools, tool_lock)
    tool_rows = {row['gitlink_path']: row for row in gitlink_lock['artifacts']}
    if set(tool_rows) != {entry['path'] for entry in config['gitlink_archives']}:
        raise ValueError('Fixed input lock differs from the original Gitlink configuration')
    closure = []
    for entry in config['gitlink_archives']:
        tool = tool_rows[entry['path']]
        if tool['gitlink_commit'] != entry['child_commit'] or tool['parent_commit'] != config['main_commit'] or tool['sha256'] != entry['sha256'] or tool['bytes'] != entry['bytes']:
            raise ValueError('Artifact-only source tool changed an original Gitlink identity')
        raw = args.tools / tool['path']
        if sha(raw) != entry['sha256'] or raw.stat().st_size != entry['bytes']:
            raise ValueError('Fixed Gitlink archive identity differs: ' + entry['path'])
        destination = source / entry['path']
        if destination.exists() and any(destination.iterdir()):
            raise ValueError('The original Gitlink location is unexpectedly populated')
        with tempfile.TemporaryDirectory(prefix='unpack-fixed-gitlink-', dir=args.build) as temporary:
            temporary = Path(temporary)
            with tarfile.open(raw) as archive:
                archive.extractall(temporary, filter='data')
            roots = list(temporary.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError('Fixed Gitlink archive has an unexpected root layout')
            child_inventory = identities(roots[0])
            if not tool['license_evidence']:
                raise ValueError('A fixed Gitlink archive lacks recorded license evidence')
            for notice in tool['license_evidence']:
                components = Path(notice['archive_member']).parts
                relative = Path(*components[1:])
                if '..' in relative.parts or child_inventory.get(relative.as_posix()) != notice['sha256'] or (roots[0] / relative).stat().st_size != notice['bytes']:
                    raise ValueError('An original fixed Gitlink license notice differs from its recorded identity')
            if not child_inventory:
                raise ValueError('Fixed Gitlink archive contains no ordinary source files')
            shutil.copytree(roots[0], destination, symlinks=True, dirs_exist_ok=True)
        closure.append({**entry, 'ordinary_files': len(child_inventory), 'file_inventory': child_inventory})
    complete_original = identities(source)
    if any(complete_original.get(k) != value for k, value in original_main.items()):
        raise ValueError('A Gitlink archive changed a main archive file')
    write(logs / 'fixed-gitlink-inputs.json', {'entries': closure,
          'scope': 'Exact parent Gitlink OIDs and complete child archive bytes; child Git-tree API 403 retained, full child Git-tree equivalence not claimed'})
    tools = {name: shutil.which(name) for name in ('gcc', 'g++')}
    if not all(tools.values()):
        raise ValueError('A declared host compiler is missing')
    private_tools, private_tool_evidence = prepare_private_build_tools(args.tools, build_tools_lock, recipe, args.build, logs)
    tools.update(private_tools)
    commands = []

    def run(label, argv, *, timeout=1800):
        command = list(map(str, argv))
        out, err = logs / (label + '.stdout'), logs / (label + '.stderr')
        started = time.monotonic()
        with out.open('wb') as stdout, err.open('wb') as stderr:
            completed = subprocess.run(command, stdout=stdout, stderr=stderr, check=False,
                                       env=dict(os.environ, RC_PARAMS=config['rc_params']), timeout=timeout)
        commands.append({'label': label, 'argv': command, 'returncode': completed.returncode,
                         'seconds': time.monotonic() - started, 'RC_PARAMS': config['rc_params'],
                         'stdout': str(out), 'stdout_sha256': sha(out),
                         'stderr': str(err), 'stderr_sha256': sha(err)})
        write(logs / 'commands.json', commands)
        print(json.dumps({'label': label, 'returncode': completed.returncode}), flush=True)
        if completed.returncode:
            raise RuntimeError(label + ' failed; complete logs retained under ' + str(logs))
        return out.read_text(errors='replace')

    upstream = None
    for kind in ('static', 'shared'):
        build = args.build / kind
        enabled = 'ON' if kind == 'static' else 'OFF'
        run(kind + '-configure', [tools['cmake'], '-S', source, '-B', build, '-G', 'Ninja',
            '-DCMAKE_MAKE_PROGRAM=' + tools['ninja'], '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER=' + tools['gcc'], '-DCMAKE_CXX_COMPILER=' + tools['g++'],
            '-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic',
            '-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic ' + ' '.join('-D' + item for item in config['test_framework_compile_definitions']),
            '-DCMAKE_INSTALL_PREFIX=' + str(args.prefix), '-DCMAKE_INSTALL_LIBDIR=lib',
            '-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON', '-DCMAKE_INSTALL_RPATH=$ORIGIN',
            '-DBUILD_SHARED_LIBS=' + ('ON' if kind == 'shared' else 'OFF'),
            '-DRC_ENABLE_TESTS=' + enabled, '-DRC_ENABLE_EXAMPLES=' + enabled,
            '-DRC_ENABLE_GTEST=ON', '-DRC_ENABLE_GMOCK=ON'])
        run(kind + '-build', [tools['cmake'], '--build', build, '--parallel', args.jobs])
        if kind == 'static':
            listed = json.loads(run('ctest-list', [tools['ctest'], '--test-dir', build,
                                                  '--show-only=json-v1']))['tests']
            if not listed or not any(t['name'] == 'rapidcheck_tests' for t in listed):
                raise RuntimeError('The enabled RapidCheck CTest entry is absent')
            junit = logs / 'upstream-tests.xml'
            output = run('ctest', [tools['ctest'], '--test-dir', build, '--verbose', '--output-on-failure',
                                  '--parallel', '1', '--timeout', '300', '--output-junit', junit])
            cases = ET.parse(junit).getroot().findall('.//testcase')
            if sorted(t['name'] for t in listed) != sorted(c.get('name') for c in cases):
                raise RuntimeError('CTest did not execute its exact complete configured list')
            if any(c.find('failure') is not None or c.find('error') is not None or c.find('skipped') is not None for c in cases):
                raise RuntimeError('An upstream CTest entry failed or was skipped')
            inner = re.search(r'All tests passed \((\d+) assertions? in (\d+) test cases?\)', output)
            if inner is None or int(inner[1]) < 1 or int(inner[2]) < 1:
                raise RuntimeError('RapidCheck/Catch did not report nonempty executed assertions and cases')
            upstream = {'status': 'passed', 'listed': len(listed), 'executed': len(cases),
                        'failures': 0, 'errors': 0, 'skipped': 0, 'test_names': [t['name'] for t in listed],
                        'inner_assertions_passed': int(inner[1]), 'inner_test_cases_passed': int(inner[2]),
                        'RC_PARAMS': config['rc_params'], 'scope': 'All enabled RapidCheck CTest entries with the fixed Catch Gitlink; examples and GoogleTest/GoogleMock integration also built',
                        'count_unit': 'CTest entries, with independently parsed nonempty Catch assertion/case counts'}
            target = args.prefix / 'libexec' / resource
            target.mkdir(parents=True)
            shutil.copy2(build / 'test/rapidcheck_tests', target / 'rapidcheck_tests')
        run(kind + '-install', [tools['cmake'], '--install', build])
    write(logs / 'upstream-summary.json', upstream)

    relocation = []
    for path in sorted((args.prefix / 'lib/pkgconfig').glob('*.pc')):
        old = path.read_text()
        if str(args.prefix) not in old:
            raise RuntimeError('Unexpected upstream installed pkg-config prefix')
        new = old.replace(str(args.prefix), '${prefix}')
        if 'prefix=${prefix}' in new:
            if new.count('prefix=${prefix}') != 1:
                raise RuntimeError('Repeated upstream pkg-config prefix declaration')
            new = new.replace('prefix=${prefix}', 'prefix=${pcfiledir}/../..', 1)
        elif not any(line.startswith('prefix=') for line in old.splitlines()):
            new = 'prefix=${pcfiledir}/../..\n' + new
        else:
            raise RuntimeError('Unrecognized upstream pkg-config prefix declaration')
        before = sha(path)
        path.write_text(new)
        relocation.append({'installed_file': path.relative_to(args.prefix).as_posix(),
                           'original_sha256': before, 'result_sha256': sha(path)})
    write(logs / 'installed-metadata-relocation.json', relocation)
    (args.prefix / 'bin').mkdir(exist_ok=True)
    for kind in ('static', 'shared'):
        executable = args.prefix / 'bin' / ('cpg-native-check' + ('' if kind == 'static' else '-shared'))
        library = args.prefix / 'lib' / ('librapidcheck' + ('.a' if kind == 'static' else '.so'))
        run(kind + '-consumer-build', [tools['g++'], '-std=c++17', '-O2', '-march=x86-64', '-mtune=generic',
            '-I' + str(args.prefix / 'include'), recipe / 'consumer.cpp', library,
            '-pthread', '-Wl,-rpath,$ORIGIN/../lib', '-o', executable])
        run(kind + '-consumer-run', [executable])
    if identities(args.source) != original_main or identities(source) != complete_original:
        raise RuntimeError('The retained original source or a fixed Gitlink source changed during the build')
    preserved = args.prefix / 'share' / resource / 'source'
    shutil.copytree(source, preserved, symlinks=True)
    if identities(preserved) != complete_original:
        raise RuntimeError('The complete retained source closure changed')
    write(logs / 'original-source-check.json', {'original_files': len(complete_original),
          'main_archive_files': len(original_main), 'changed_original_files': [],
          'complete_preserved_source': True, 'original_inventory': complete_original,
          'gitlink_closure_scope': 'Exact parent commit Gitlinks, full raw child archives; no unavailable child Git-tree API claim'})
    evidence = args.prefix / 'share/compiler-playground' / resource
    evidence.mkdir(parents=True)
    for name in ('build.py', 'check.py', 'consumer.cpp', 'config.json', 'original-package.json', 'resolved-sources.json', 'gitlink-recovery.json', 'fixed-gitlink-artifacts.json', 'prepare_fixed_gitlinks.py', 'source-artifacts.json',
                 'build-tool-artifacts.json', 'private_build_tools.py', 'prepare_source_tools.py', 'cmake-3.28.3-SHA-256.txt'):
        shutil.copy2(recipe / name, evidence / name)
    # Raw supplemental archives remain in the source artifact tools namespace.
    # The binary prefix retains every original expanded source and license file.
    verify_tools(args.tools, tool_lock)
    verify_after_use(private_tool_evidence, logs)
    write(evidence / 'profile.json', {'resource_id': resource, 'source_modified': False,
          'main_commit': config['main_commit'], 'libraries': ['static', 'shared'], 'upstream': upstream,
          'test_framework_compile_definitions': config['test_framework_compile_definitions'],
          'source_tools_lock_sha256': sha(recipe / 'source-artifacts.json'),
          'private_build_tool_inputs_sha256': sha(recipe / 'build-tool-artifacts.json'),
          'build_only_precompiled_tools_not_resource_qualifications': True,
          'source_files': len(complete_original), 'installed_metadata_relocations': relocation,
          'unperformed': config['unperformed']})


if __name__ == '__main__':
    main()
