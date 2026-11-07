#!/usr/bin/env python3
"""Bounded OpenCilk reduction and Tapir IR qualification; no downloads."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def qualify(prefix, work):
    prefix, work = Path(prefix).resolve(), Path(work).resolve()
    if prefix == work or prefix in work.parents or work in prefix.parents:
        raise ValueError('Use disjoint installation and work directories')
    work.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name('reduction.c')
    clang = prefix / 'bin/clang'
    opt = prefix / 'bin/opt'
    gcc = shutil.which('gcc')
    if not gcc:
        raise RuntimeError('A host GCC installation with C headers/libraries is required')
    evidence = {'schema_version': 1, 'resource': 'opencilk',
                'scope': 'CPU C11 cilk_for reducer, serial/Python oracles and Tapir IR',
                'compiler_from_source': False, 'hardware_accelerator_qualified': False,
                'official_benchmark_qualified': False, 'commands': [], 'cases': [],
                'negative_controls': [], 'fixture_sha256': digest(source)}

    def run(argv, *, expected=0, env=None, timeout=600):
        start = time.monotonic()
        proc = subprocess.run([str(x) for x in argv], cwd=work, capture_output=True,
                              text=True, errors='replace', timeout=timeout,
                              env={**os.environ, **(env or {})})
        index = len(evidence['commands'])
        out = work / f'{index:03d}.stdout.txt'
        err = work / f'{index:03d}.stderr.txt'
        out.write_text(proc.stdout)
        err.write_text(proc.stderr)
        evidence['commands'].append({'argv': [str(x) for x in argv],
            'returncode': proc.returncode, 'elapsed_seconds': time.monotonic() - start,
            'environment_overrides': env or {}, 'stdout': out.name, 'stderr': err.name,
            'stdout_sha256': digest(out), 'stderr_sha256': digest(err)})
        if expected is not None and proc.returncode != expected:
            raise RuntimeError(f'Unexpected return code {proc.returncode}: {argv}; {proc.stderr[-3000:]}')
        return proc

    try:
        evidence['compiler_version'] = run([clang, '--version']).stdout
        evidence['serial_compiler_version'] = run([gcc, '--version']).stdout
        serial, parallel, mutant = (work / x for x in ('serial', 'parallel', 'mutant'))
        common = ['-std=c11', '-O2']
        run([gcc, *common, '-DCPG_SERIAL', source, '-o', serial])
        run([clang, *common, '-fopencilk', source, '-o', parallel])
        run([clang, *common, '-fopencilk', '-DCPG_BAD_RESULT', source, '-o', mutant])
        ir = work / 'reduction.tapir.ll'
        run([clang, '-std=c11', '-O1', '-fopencilk', '-S', '-emit-llvm',
             '-Xclang', '-disable-llvm-passes', source, '-o', ir])
        text = ir.read_text()
        evidence['tapir_ir'] = {'sha256': digest(ir), 'path': ir.name,
            'detach': len(re.findall(r'\bdetach within\b', text)),
            'reattach': len(re.findall(r'\breattach within\b', text)),
            'sync': len(re.findall(r'\bsync within\b', text))}
        if not all(evidence['tapir_ir'][key] > 0 for key in ('detach', 'reattach', 'sync')):
            raise RuntimeError('Generated IR is missing required Tapir control-flow instructions')
        run([opt, '-passes=verify', '-disable-output', ir])
        fixtures = [(n, seed) for n in (0, 1, 7, 257, 8193, 131073) for seed in (0, 31)]
        oracles = {}
        for n, seed in fixtures:
            oracle = sum(((i * 17 + seed * 29) % 257) - 128 for i in range(n))
            observed = json.loads(run([serial, n, seed]).stdout)
            if observed['sum'] != oracle:
                raise RuntimeError('Independent serial implementation differs from Python oracle')
            oracles[n, seed] = oracle
        for workers in (1, 2, 4):
            for n, seed in fixtures:
                observed = json.loads(run([parallel, n, seed],
                                         env={'CILK_NWORKERS': str(workers)}).stdout)
                expected = oracles[n, seed]
                if observed['sum'] != expected or observed['workers'] != workers:
                    raise RuntimeError('Parallel result or configured worker count differs')
                evidence['cases'].append({**observed, 'expected_sum': expected,
                                          'configured_workers': workers, 'status': 'passed'})
        bad = json.loads(run([mutant, 8193, 31], env={'CILK_NWORKERS': '2'}).stdout)
        if bad['sum'] == oracles[8193, 31]:
            raise RuntimeError('Oracle failed to reject deliberately corrupted result')
        evidence['negative_controls'].append({'name': 'wrong_result', 'status': 'rejected',
                                              'observed': bad['sum'], 'expected': oracles[8193, 31]})
        rejected = run([gcc, '-std=c11', '-fsyntax-only', '-I' + str(prefix / 'include'), source],
                       expected=None)
        if rejected.returncode == 0:
            raise RuntimeError('Non-OpenCilk compiler unexpectedly accepted Cilk extensions')
        evidence['negative_controls'].append({'name': 'non_cilk_compiler', 'status': 'rejected'})
        for bad_arg in ('-1', '1000001', 'invalid'):
            run([parallel, bad_arg, '0'], expected=2)
        evidence['negative_controls'].append({'name': 'invalid_inputs', 'status': 'rejected', 'count': 3})
        evidence['status'] = 'passed'
        evidence['parallel_cases_passed'] = len(evidence['cases'])
        evidence['serial_cases_passed'] = len(oracles)
        evidence['observed_worker_mask_union'] = 0
        for row in evidence['cases']:
            evidence['observed_worker_mask_union'] |= row['worker_mask']
        return evidence
    except BaseException as error:
        evidence['status'] = 'failed'
        evidence['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Optimized Python mode is not accepted for qualification')
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--work', required=True)
    args = parser.parse_args()
    result = qualify(args.prefix, args.work)
    print(json.dumps({'status': result['status'],
                      'parallel_cases': result['parallel_cases_passed'],
                      'serial_cases': result['serial_cases_passed'],
                      'tapir_ir': result['tapir_ir'],
                      'negative_controls': len(result['negative_controls'])}))
