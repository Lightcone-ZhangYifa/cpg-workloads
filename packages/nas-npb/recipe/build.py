#!/usr/bin/env python3
"""Build original NPB 3.4.4 OpenMP C IS/DC programs, classes S and W."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from check import validate_output


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
    logs = args.build / 'native-logs'
    logs.mkdir(parents=True)
    original = identities(args.source)
    if not original:
        raise RuntimeError('Original NPB source is empty')
    commands = []

    def run(label, argv, *, cwd=None, env=None, timeout=600):
        command = list(map(str, argv))
        out, err = logs / (label + '.stdout'), logs / (label + '.stderr')
        started = time.monotonic()
        with out.open('wb') as stdout, err.open('wb') as stderr:
            completed = subprocess.run(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                       timeout=timeout, check=False)
        commands.append({'label': label, 'argv': command, 'cwd': str(cwd) if cwd else None,
                         'returncode': completed.returncode, 'seconds': time.monotonic() - started,
                         'stdout': str(out), 'stdout_sha256': sha(out),
                         'stderr': str(err), 'stderr_sha256': sha(err)})
        write(logs / 'commands.json', commands)
        print(json.dumps({'label': label, 'returncode': completed.returncode}), flush=True)
        if completed.returncode:
            raise RuntimeError(label + ' failed; retained original output: ' + str(logs))
        return out.read_text(errors='replace')

    tests = []
    configurations = []
    (args.prefix / 'bin').mkdir(parents=True, exist_ok=True)
    for size_class in config['classes']:
        source = args.build / ('class-' + size_class)
        shutil.copytree(args.source, source, symlinks=True)
        omp = source / 'NPB3.4-OMP'
        site = omp / 'config/make.def'
        template = omp / 'config/make.def.template'
        old = template.read_text()
        expected = 'CFLAGS\t= -O3 -fopenmp'
        if old.count(expected) != 1 or site.exists():
            raise RuntimeError('Unexpected original NPB platform configuration')
        new = old.replace(expected, 'CFLAGS\t= -O2 -fopenmp -march=x86-64 -mtune=generic -DIN_CORE')
        site.write_text(new)
        configurations.append({'class': size_class, 'source_template_sha256': sha(template),
                               'generated_site_config_sha256': sha(site),
                               'generated_path': 'NPB3.4-OMP/config/make.def',
                               'change': 'New site configuration from original template; original sources unchanged'})
        for benchmark in config['benchmarks']:
            run(benchmark + '-' + size_class + '-build', ['make', '-C', omp, benchmark, 'CLASS=' + size_class,
                                                         '-j' + str(args.jobs)])
            name = benchmark + '.' + size_class + '.x'
            shutil.copy2(omp / 'bin' / name, args.prefix / 'bin' / name)
            for threads in config['threads']:
                with tempfile.TemporaryDirectory(prefix='cpg-npb-source-run-', dir=args.build) as temporary:
                    output = run(benchmark + '-' + size_class + '-threads-' + str(threads),
                                 [args.prefix / 'bin' / name], cwd=temporary,
                                 env=dict(os.environ, OMP_NUM_THREADS=str(threads), OMP_DYNAMIC='FALSE'))
                case = validate_output(output, benchmark, size_class, threads)
                tests.append({'name': name + '-threads-' + str(threads), **case})
    upstream = {'status': 'passed', 'scope': 'Original OpenMP C IS/DC programs, classes S and W, each at one and two threads',
                'listed': len(tests), 'executed': len(tests), 'failures': 0, 'errors': 0, 'skipped': 0,
                'test_names': [t['name'] for t in tests], 'cases': tests,
                'count_unit': 'Actual program/class/thread runs validated by the upstream built-in verifier'}
    write(logs / 'upstream-summary.json', upstream)
    write(logs / 'generated-site-configurations.json', configurations)
    preserved = args.prefix / 'share/nas-npb/source'
    shutil.copytree(args.source, preserved, symlinks=True)
    after = identities(args.source)
    if after != original or identities(preserved) != original:
        raise RuntimeError('The complete original source copy changed')
    write(logs / 'original-source-check.json', {'original_files': len(original),
          'original_logical_bytes': sum((args.source / p).stat().st_size for p in original),
          'changed_original_files': [], 'complete_preserved_source': True, 'original_inventory': original})
    evidence = args.prefix / 'share/compiler-playground/nas-npb'
    evidence.mkdir(parents=True)
    for name in ('build.py', 'check.py', 'config.json', 'original-package.json', 'resolved-sources.json'):
        shutil.copy2(recipe / name, evidence / name)
    write(evidence / 'profile.json', {'resource_id': 'nas-npb', 'upstream_version': '3.4.4',
          'source_modified': False, 'dc_processing_mode': config['dc_processing_mode'], 'retained_source_files': len(original), 'upstream': upstream,
          'generated_site_configurations': configurations, 'unperformed': config['unperformed']})


if __name__ == '__main__':
    main()
