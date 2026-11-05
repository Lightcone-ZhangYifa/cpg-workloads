#!/usr/bin/env python3
"""Build a declared CPU profile in a complete independent upstream copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import time

REVISIONS = {
    'stream': '6703f7504a38a8da96b353cadafa64d3c2d7a2d3',
    'rsbench': '34b644787ea9af4fb188e1253da72e09bbed9989',
    'epcc-openmp': '94628c25ef2b37b2e9bcc3ed7a6f7cd5cbac459a',
    'xsbench': 'ba08e5221af6106252b866e50ea123c69d31a4e2',
    'quicksilver': 'eb68bb8d6fc53de1f65011d4e79ff2ed0dd60f3b',
}
FILE_COUNTS = {'stream': 8, 'rsbench': 58, 'epcc-openmp': 46, 'xsbench': 67, 'quicksilver': 159}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    found = {}
    for p in sorted(root.rglob('*')):
        st = p.lstat()
        if stat.S_ISDIR(st.st_mode):
            continue
        if not stat.S_ISREG(st.st_mode):
            raise ValueError('The reviewed original archives contain only ordinary files: ' + str(p))
        found[p.relative_to(root).as_posix()] = {'sha256': digest(p), 'bytes': st.st_size,
                                                'mode': stat.S_IMODE(st.st_mode)}
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--resource', choices=sorted(REVISIONS), required=True)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--build', type=Path, required=True)
    ap.add_argument('--prefix', type=Path, required=True)
    ap.add_argument('--jobs', type=int, default=2)
    args = ap.parse_args()
    assert 1 <= args.jobs <= 4
    source, build, prefix = args.source.resolve(strict=True), args.build.resolve(), args.prefix.resolve()
    assert source not in (build, prefix) and source not in build.parents and source not in prefix.parents
    before = inventory(source)
    assert len(before) == FILE_COUNTS[args.resource], (args.resource, len(before))
    work = build / 'complete-upstream-build-copy'
    shutil.copytree(source, work)
    assert inventory(work) == before
    for p in work.rglob('*'):
        if p.is_file():
            q = source / p.relative_to(work)
            assert p.stat().st_nlink == q.stat().st_nlink == 1
            assert (p.stat().st_dev, p.stat().st_ino) != (q.stat().st_dev, q.stat().st_ino)
    logs = build / 'native-build-logs'
    logs.mkdir(exist_ok=False)
    (logs / 'original-source-before.json').write_text(json.dumps(before, sort_keys=True, indent=2) + '\n')
    (prefix / 'bin').mkdir(parents=True, exist_ok=True)
    kind, generated = args.resource, []
    if kind == 'stream':
        argv = ['gcc', '-O2', '-fopenmp', '-DSTREAM_ARRAY_SIZE=1000000', '-DNTIMES=10',
                '-o', str(work / 'stream'), str(work / 'stream.c')]
        products = {'stream': work / 'stream'}
    elif kind == 'rsbench':
        argv = ['make', '-C', str(work / 'openmp-threading'), '-j' + str(args.jobs), 'CC=gcc']
        products = {'rsbench': work / 'openmp-threading/rsbench'}
    elif kind == 'epcc-openmp':
        argv = ['make', '-C', str(work / 'openmpbench_C_v31'), '-j' + str(args.jobs), 'CC=gcc',
                'CFLAGS=-O2 -fopenmp', 'CFLAGS_CRAY=-O2 -fopenmp', 'LDFLAGS=-fopenmp',
                'syncbench', 'schedbench', 'taskbench']
        products = {x: work / 'openmpbench_C_v31' / x for x in ('syncbench', 'schedbench', 'taskbench')}
    elif kind == 'xsbench':
        argv = ['make', '-C', str(work / 'openmp-threading'), '-j' + str(args.jobs), 'CC=gcc',
                'OPENMP=yes', 'OPTIMIZE=yes', 'MPI=no', 'AML=no']
        products = {'XSBench': work / 'openmp-threading/XSBench'}
    else:
        dep = work / 'src/.depend'
        assert not dep.exists()
        dep.touch()
        generated.append({'path': 'src/.depend', 'sha256': digest(dep), 'bytes': 0,
            'reason': 'A one-shot independent build does not need incremental makedepend dependency regeneration.'})
        argv = ['make', '-C', str(work / 'src'), '-j' + str(args.jobs), 'CXX=g++',
                'CXXFLAGS=-std=c++11 -O2', 'CPPFLAGS=-include cstdint', 'LDFLAGS=',
                'GITHASH=' + REVISIONS[kind], 'GITVERS=pinned-source-archive', 'qs']
        products = {'qs': work / 'src/qs'}
    started = time.monotonic()
    with (logs / 'compile.stdout').open('wb') as stdout, (logs / 'compile.stderr').open('wb') as stderr:
        run = subprocess.run(argv, stdout=stdout, stderr=stderr, cwd=build,
                             env={**os.environ, 'LC_ALL': 'C'}, timeout=600, check=False)
    elapsed = round(time.monotonic() - started, 6)
    receipt = {'argv': argv, 'returncode': run.returncode, 'seconds': elapsed,
               'generated_build_inputs': generated,
               'quicksilver_forced_header': 'cstdint' if kind == 'quicksilver' else None}
    (logs / 'command.json').write_text(json.dumps(receipt, indent=2) + '\n')
    assert run.returncode == 0, ('Compilation failed; complete logs retained', str(logs))
    for name, file in products.items():
        assert file.is_file() and not file.is_symlink() and os.access(file, os.X_OK)
        shutil.copy2(file, prefix / 'bin' / name)
        (prefix / 'bin' / name).chmod(0o755)
    if kind == 'epcc-openmp':
        launcher = prefix / 'bin/epcc-openmp'
        launcher.write_text('#!/bin/sh\nset -eu\nsub=${1:-}\ncase "$sub" in syncbench|schedbench|taskbench) shift;; *) echo "usage: epcc-openmp syncbench|schedbench|taskbench [options]" >&2; exit 64;; esac\nexec "$(dirname "$0")/$sub" "$@"\n')
        launcher.chmod(0o755)
    notices = []
    for rel, ident in before.items():
        if any(token in Path(rel).name.lower() for token in ('license', 'licence', 'copying', 'copyright', 'notice')):
            dest = prefix / 'share/licenses' / kind / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, dest)
            notices.append({'path': rel, **ident})
    assert notices, 'Original license notice is required'
    for name in ('README.md', 'CHANGES.txt'):
        if (source / name).is_file():
            dest = prefix / 'share/doc' / kind / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, dest)
    if kind == 'quicksilver':
        for name in ('AllAbsorb/allAbsorb.inp', 'AllEscape/allEscape.inp'):
            dest = prefix / 'share/quicksilver/Examples' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / 'Examples' / name, dest)
    after = inventory(source)
    (logs / 'original-source-after.json').write_text(json.dumps(after, sort_keys=True, indent=2) + '\n')
    assert before == after, 'Compilation modified original prepared source materials'
    observations = {}
    for cmd in ('gcc', 'g++', 'make', 'python3'):
        exe = shutil.which(cmd)
        if exe:
            observation = subprocess.run([exe, '--version'], text=True, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, timeout=10)
            observations[cmd] = {'executable': exe, 'sha256': digest(Path(exe).resolve()),
                                 'returncode': observation.returncode, 'version_output': observation.stdout}
    profile = {'format': 'cpg-explicit-native-host-profile-v1', 'resource_id': 'dataset-ref.' + kind,
               'source_commit': REVISIONS[kind], 'original_source_files': len(before),
               'original_source_unchanged': True, 'independent_complete_build_copy': True,
               'os': platform.system(), 'arch': platform.machine(), 'kernel': platform.release(),
               'toolchain': observations, 'build_command': argv, 'build_seconds': elapsed,
               'installed_programs': {n: {'sha256': digest(prefix / 'bin' / n),
                                        'bytes': (prefix / 'bin' / n).stat().st_size} for n in products},
               'notices': notices, 'generated_build_inputs': generated,
               'runtime_scope': 'CPU serial' if kind == 'quicksilver' else 'CPU OpenMP',
               'official_benchmark_qualified': False, 'oci_qualified': False,
               'physical_hardware_qualified': False, 'other_profiles_qualified': False}
    dest = prefix / 'share/compiler-playground' / (kind + '-native-profile.json')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(profile, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': 'built_and_installed', 'resource_id': profile['resource_id'],
                      'source_unchanged': True, 'source_files': len(before),
                      'build_seconds': elapsed, 'programs': profile['installed_programs']}))


if __name__ == '__main__':
    main()
