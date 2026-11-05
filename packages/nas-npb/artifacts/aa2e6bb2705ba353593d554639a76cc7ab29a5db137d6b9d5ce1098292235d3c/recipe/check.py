#!/usr/bin/env python3
"""Check bounded NPB semantics with upstream verification and exact identities."""
from __future__ import annotations
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def validate_output(output, benchmark, size_class, threads):
    required = [r'^\s*' + benchmark.upper() + r' Benchmark Completed\s*$',
                r'^\s*Class\s*=\s*' + size_class + r'\s*$',
                r'^\s*Total threads\s*=\s*' + str(threads) + r'\s*$',
                r'^\s*Verification\s*=\s*SUCCESSFUL\s*$',
                r'^\s*Version\s*=\s*3\.4\.4\s*$']
    for pattern in required:
        if len(re.findall(pattern, output, re.M)) != 1:
            raise ValueError('NPB output lacks its exact successful identity: ' + pattern)
    result = {'benchmark': benchmark, 'class': size_class, 'threads': threads,
              'upstream_verification': 'SUCCESSFUL', 'version': '3.4.4'}
    if benchmark == 'is':
        size = 65536 if size_class == 'S' else 1048576
        if not re.search(r'^\s*Size\s*=\s*' + str(size) + r'\s*$', output, re.M):
            raise ValueError('IS executed another problem size')
        if not re.search(r'^\s*Iterations\s*=\s*10\s*$', output, re.M):
            raise ValueError('IS did not execute all ten benchmark iterations')
        result.update(problem_size=size, iterations=10)
    else:
        checksum = 464620213 if size_class == 'S' else 1401796434318
        matches = re.findall(r'^\s*Checksum\s*=\s*([0-9.eE+-]+)\s*$', output, re.M)
        if len(matches) != 1 or Decimal(matches[0]) != Decimal(checksum):
            raise ValueError('DC result differs from the checksum in the locked original upstream source')
        result['upstream_reference_checksum'] = checksum
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve(strict=True)
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    profile = json.loads((prefix / 'share/compiler-playground/nas-npb/profile.json').read_text())
    if profile['resource_id'] != 'nas-npb' or profile['upstream_version'] != '3.4.4':
        raise ValueError('Installed NPB profile identity differs')
    environment = dict(os.environ, LC_ALL='C', OMP_DYNAMIC='FALSE')
    for key in list(environment):
        if key.startswith('LD_'):
            environment.pop(key)
    report = {'resource_id': 'nas-npb', 'status': 'running', 'cases': [], 'commands': [],
              'scope': 'Selected original OpenMP C IS/DC configurations; no MPI, Fortran or performance qualification'}

    def run(argv, *, cwd, threads, expected=0):
        command = list(map(str, argv))
        completed = subprocess.run(command, cwd=cwd, env=dict(environment, OMP_NUM_THREADS=str(threads)),
                                   capture_output=True, text=True, timeout=600)
        report['commands'].append({'argv': command, 'returncode': completed.returncode,
                                   'threads': threads, 'stdout': completed.stdout, 'stderr': completed.stderr})
        if completed.returncode != expected:
            raise RuntimeError('Unexpected NPB exit status: ' + command[0])
        return completed

    try:
        for benchmark in config['benchmarks']:
            for size_class in config['classes']:
                executable = prefix / 'bin' / (benchmark + '.' + size_class + '.x')
                for threads in config['threads']:
                    with tempfile.TemporaryDirectory(prefix='cpg-npb-binary-run-') as temporary:
                        completed = run([executable], cwd=temporary, threads=threads)
                    case = validate_output(completed.stdout, benchmark, size_class, threads)
                    # The verifier must reject a claim of success that has been
                    # replaced with the upstream unsuccessful token.
                    rejected = False
                    try:
                        validate_output(completed.stdout.replace('SUCCESSFUL', 'UNSUCCESSFUL'), benchmark, size_class, threads)
                    except ValueError:
                        rejected = True
                    if not rejected:
                        raise RuntimeError('Semantic output validator accepted an unsuccessful upstream result')
                    case['unsuccessful_result_rejected'] = True
                    report['cases'].append(case)
                with tempfile.TemporaryDirectory(prefix='cpg-npb-loader-') as temporary:
                    linked = run(['ldd', executable], cwd=temporary, threads=1)
                    if 'not found' in linked.stdout or 'libgomp.so' not in linked.stdout:
                        raise RuntimeError('NPB OpenMP runtime is absent')
        with tempfile.TemporaryDirectory(prefix='cpg-npb-invalid-input-') as temporary:
            failed = run([prefix / 'bin/dc.S.x', 'not-a-memory-size'], cwd=temporary, threads=1, expected=1)
            if 'Usage:' not in failed.stderr:
                raise RuntimeError('Invalid DC argument had no expected refusal diagnostic')
        report.update(status='passed', actual_runs=len(report['cases']), invalid_argument_rejected=True)
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
