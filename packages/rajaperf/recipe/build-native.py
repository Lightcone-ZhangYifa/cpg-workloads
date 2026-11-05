#!/usr/bin/env python3
"""Build the complete fixed RAJAPerf tree with all sequential CPU kernels."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET

from native_inventory import inventory, sha, execution_matrix
from prepare_source_tools import verify_tools
from private_build_tools import prepare, verify_after_use


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'build', 'prefix', 'tools'):
        parser.add_argument('--' + key, required=True, type=Path)
    parser.add_argument('--jobs', required=True, type=int)
    args = parser.parse_args()
    assert 1 <= args.jobs <= 2
    recipe = Path(__file__).parent
    logs = args.build / 'native-logs'
    logs.mkdir()
    source_lock = json.loads((recipe / 'source-closure-locks.json').read_text())
    raw_lock = json.loads((recipe / 'source-closure-artifacts.json').read_text())
    build_lock = json.loads((recipe / 'build-tool-artifacts.json').read_text())
    tool_lock = json.loads((recipe / 'source-artifacts.json').read_text())
    assert tool_lock['artifacts'] == raw_lock['artifacts'] + build_lock['artifacts']
    assert tool_lock['directories'] == raw_lock['directories'] + build_lock['directories']
    verify_tools(args.tools, tool_lock)
    raw_by_hash = {row['sha256']: args.tools / row['path'] for row in raw_lock['artifacts']}
    source = args.build / 'complete-original-source'
    shutil.copytree(args.source, source, symlinks=True)
    main_files = {p.relative_to(args.source).as_posix(): sha(p)
                  for p in args.source.rglob('*') if p.is_file() and not p.is_symlink()}
    mounts = []

    def fill(key, destination, ancestry, is_root=False):
        assert key not in ancestry
        node = source_lock['nodes'][key]
        if not is_root:
            raw = raw_by_hash[node['sha256']]
            assert sha(raw) == node['sha256'] and raw.stat().st_size == node['bytes']
            if destination.exists():
                assert destination.is_dir() and not destination.is_symlink() and not list(destination.iterdir())
                destination.rmdir()
            with tempfile.TemporaryDirectory(prefix='fixed-archive-', dir=args.build) as temporary:
                temporary = Path(temporary)
                with tarfile.open(raw) as archive:
                    archive.extractall(temporary, filter='data')
                roots = list(temporary.iterdir())
                assert len(roots) == 1 and roots[0].is_dir() and not roots[0].is_symlink()
                shutil.copytree(roots[0], destination, symlinks=True)
        for extra in source_lock['extra_files'].get(key, []):
            relative = PurePosixPath(extra['path'])
            assert not relative.is_absolute() and '..' not in relative.parts
            target = destination / relative
            assert not os.path.lexists(target)
            raw = raw_by_hash[extra['sha256']]
            data = raw.read_bytes()
            assert len(data) == extra['bytes'] and hashlib.sha256(data).hexdigest() == extra['sha256']
            assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == extra['git_blob_sha1']
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            target.chmod(extra['mode'])
        for notice in node['notice_paths']:
            assert (destination / notice).is_file()
        mounts.append({'node': key, 'path': destination.relative_to(source).as_posix(),
                       'archive_sha256': node['sha256'], 'notices': node['notice_paths']})
        for edge in source_lock['edges']:
            if edge['parent'] == key:
                assert edge['gitlink_mode'] == '160000'
                path = PurePosixPath(edge['path'])
                assert not path.is_absolute() and '..' not in path.parts
                fill(edge['child'], destination / path, ancestry + [key])

    fill(source_lock['root'], source, [], True)
    expected = json.loads((recipe / 'material-manifest.json').read_text())['files']
    assert inventory(source) == expected, 'Complete original recursive source differs from the original material manifest'
    write(logs / 'source-closure.json', {'status': 'passed', 'mounts': mounts,
          'files': expected, 'unchanged_original_material_inventory': True})
    tools, tool_evidence = prepare(args.tools, build_lock, recipe, args.build, logs)
    tools.update(gcc=shutil.which('gcc'), gxx=shutil.which('g++'))
    assert tools['gcc'] and tools['gxx']
    commands = []
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('LD_', 'GTEST_', 'GMOCK_')) and k != 'RAJA_PERFSUITE_UNIT_TEST'}
    env.update(LC_ALL='C', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')

    def run(label, argv, timeout=900):
        argv = list(map(str, argv))
        out, err = logs / (label + '.stdout'), logs / (label + '.stderr')
        started = time.monotonic()
        try:
            with out.open('wb') as stdout, err.open('wb') as stderr:
                result = subprocess.run(argv, stdout=stdout, stderr=stderr, env=env,
                                        cwd=args.build, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            commands.append({'label': label, 'argv': argv, 'returncode': None,
                             'status': 'timeout', 'timeout_seconds': timeout,
                             'seconds': time.monotonic() - started, 'stdout': str(out), 'stderr': str(err),
                             'stdout_sha256': sha(out), 'stderr_sha256': sha(err)})
            write(logs / 'commands.json', commands)
            raise
        commands.append({'label': label, 'argv': argv, 'returncode': result.returncode,
                         'seconds': time.monotonic() - started, 'stdout': str(out), 'stderr': str(err),
                         'stdout_sha256': sha(out), 'stderr_sha256': sha(err)})
        write(logs / 'commands.json', commands)
        print(json.dumps({'label': label, 'returncode': result.returncode}), flush=True)
        assert result.returncode == 0, label + ' failed; original logs retained'
        return out.read_text(errors='replace')

    build = args.build / 'sequential-cpu'
    flags = ['-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG',
             '-DCMAKE_C_FLAGS_RELEASE=-O2 -DNDEBUG', '-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic',
             '-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic', '-DBUILD_SHARED_LIBS=OFF',
             '-DENABLE_TESTS=ON', '-DRAJA_PERFSUITE_ENABLE_TESTS=ON', '-DPERFSUITE_RUN_SHORT_TEST=OFF',
             '-DENABLE_RAJA_SEQUENTIAL=ON', '-DENABLE_OPENMP=OFF', '-DENABLE_MPI=OFF',
             '-DENABLE_CUDA=OFF', '-DENABLE_HIP=OFF', '-DENABLE_KOKKOS=OFF', '-DRAJA_ENABLE_SYCL=OFF',
             '-DENABLE_TARGET_OPENMP=OFF', '-DFETCHCONTENT_FULLY_DISCONNECTED=ON',
             '-DCMAKE_INSTALL_PREFIX=' + str(args.prefix), '-DCMAKE_INSTALL_LIBDIR=lib',
             '-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON', '-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib']
    run('configure', [tools['cmake'], '-S', source, '-B', build, '-G', 'Ninja',
        '-DCMAKE_MAKE_PROGRAM=' + tools['ninja'], '-DCMAKE_C_COMPILER=' + tools['gcc'],
        '-DCMAKE_CXX_COMPILER=' + tools['gxx'], *flags], 120)
    run('build', [tools['cmake'], '--build', build, '--parallel', args.jobs], 1200)
    tests = json.loads(run('ctest-list', [tools['ctest'], '--test-dir', build, '--show-only=json-v1']))['tests']
    assert tests and any('test-raja-perf-suite' in row['name'] for row in tests)
    junit = logs / 'upstream-tests.xml'
    test_output = run('ctest', [tools['ctest'], '--test-dir', build, '--verbose', '--output-on-failure',
                      '--parallel', '1', '--timeout', '900', '--output-junit', junit], 1000)
    cases = ET.parse(junit).getroot().findall('.//testcase')
    assert sorted(c.get('name') for c in cases) == sorted(t['name'] for t in tests)
    assert not any(c.find('failure') is not None or c.find('error') is not None or c.find('skipped') is not None for c in cases)
    assert 'ShortSuiteTest.Basic' in test_output and '[  PASSED  ]' in test_output
    upstream = {'status': 'passed', 'listed': len(tests), 'executed': len(cases),
                'failures': 0, 'errors': 0, 'skipped': 0, 'test_names': [row['name'] for row in tests],
                'scope': 'Complete configured upstream suite, all sequential CPU kernels; no short-test macro, test filter or kernel exclusions.'}
    write(logs / 'upstream-summary.json', upstream)
    run('install', [tools['cmake'], '--install', build])
    test_bins = [p for p in build.rglob('test-raja-perf-suite.exe') if p.is_file()]
    assert len(test_bins) == 1
    target = args.prefix / 'libexec/rajaperf'
    target.mkdir(parents=True)
    shutil.copy2(test_bins[0], target / test_bins[0].name)
    preserved = args.prefix / 'share/rajaperf/source'
    shutil.copytree(source, preserved, symlinks=True)
    assert inventory(source) == inventory(preserved) == expected
    assert main_files == {p.relative_to(args.source).as_posix(): sha(p) for p in args.source.rglob('*') if p.is_file() and not p.is_symlink()}
    write(logs / 'original-source-check.json', {'original_files': sum(r['kind'] == 'file' for r in expected),
          'main_archive_files': len(main_files), 'changed_original_files': [], 'complete_preserved_source': True,
          'recursive_gitlink_mounts': mounts, 'original_inventory': expected})
    evidence = args.prefix / 'share/compiler-playground/rajaperf'
    shutil.copytree(recipe, evidence)
    text = (source / 'src/common/RAJAPerfSuite.cpp').read_text()
    block = text.split('static const std::string KernelNames [] =', 1)[1].split('};', 1)[0]
    kernels = sorted(set(re.findall(r'std::string\("([A-Za-z]+_[A-Za-z0-9_]+)"\)', block)) -
                     {'Comm_HALO_SENDRECV', 'Comm_HALO_EXCHANGE', 'Comm_HALO_EXCHANGE_FUSED'})
    assert len(kernels) >= 70
    matrix = execution_matrix(test_output)
    assert matrix['kernels'] == kernels
    write(evidence / 'profile.json', {'resource_id': 'rajaperf', 'upstream': upstream,
          'kernels': kernels, 'variants': ['Base_Seq', 'Lambda_Seq', 'RAJA_Seq'],
          'upstream_executed_matrix': matrix,
          'upstream_matrix_basis': 'Actual complete original CTest Executor progress, with explicit supported/unsupported variants and each tuning run; no Cartesian-product assumption.',
          'runtime_probe_problem_size': 4096, 'runtime_probe_repetitions': 3,
          'source_files': 6464, 'source_modified': False, 'configuration': flags,
          'unperformed': ['OpenMP', 'MPI', 'GPU', 'Kokkos execution', 'official performance score', 'OCI', 'isolated hardware']})
    run('installed-native-probe', [sys.executable, '-B', recipe / 'check-native.py', '--prefix', args.prefix], 300)
    verify_tools(args.tools, tool_lock)
    verify_after_use(tool_evidence, logs)


if __name__ == '__main__':
    main()
