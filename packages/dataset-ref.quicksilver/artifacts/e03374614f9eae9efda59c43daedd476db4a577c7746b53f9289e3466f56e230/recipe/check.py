#!/usr/bin/env python3
"""Run the original reviewed CPU workloads; retain complete program output."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--resource', choices=('stream', 'rsbench', 'epcc-openmp', 'xsbench', 'quicksilver'), required=True)
    ap.add_argument('--prefix', type=Path, required=True)
    args = ap.parse_args()
    root, kind, results = args.prefix, args.resource, []
    profile = json.loads((root / 'share/compiler-playground' / (kind + '-native-profile.json')).read_text())
    for name, identity in profile['installed_programs'].items():
        binary = root / 'bin' / name
        assert binary.is_file() and not binary.is_symlink() and os.access(binary, os.X_OK)
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == identity['sha256']
    assert list((root / 'share/licenses' / kind).rglob('*')), 'Original notices are required'

    def execute(argv, *, threads=None, cwd=None, timeout=120):
        environment = {**os.environ, 'LC_ALL': 'C'}
        if threads is not None:
            environment['OMP_NUM_THREADS'] = str(threads)
        completed = subprocess.run([str(x) for x in argv], cwd=cwd or root, env=environment,
                                   capture_output=True, text=True, errors='replace', timeout=timeout)
        print('CPG_PROGRAM_ARGV ' + json.dumps([str(x) for x in argv]), flush=True)
        print('CPG_PROGRAM_STDOUT_BEGIN\n' + completed.stdout + '\nCPG_PROGRAM_STDOUT_END', flush=True)
        print('CPG_PROGRAM_STDERR_BEGIN\n' + completed.stderr + '\nCPG_PROGRAM_STDERR_END', flush=True)
        proof = {'argv': [str(x) for x in argv], 'returncode': completed.returncode,
                 'stdout_sha256': hashlib.sha256(completed.stdout.encode()).hexdigest(),
                 'stderr_sha256': hashlib.sha256(completed.stderr.encode()).hexdigest(),
                 'threads_requested': threads}
        results.append(proof)
        assert completed.returncode == 0, proof
        return completed.stdout, completed.stderr, proof

    if kind == 'stream':
        for threads in (1, 2):
            out, err, proof = execute([root / 'bin/stream'], threads=threads)
            assert 'Solution Validates: avg error less than' in out and 'Solution Did Not Validate' not in out
            assert '1000000' in out and '10 times' in out
            proof.update(status='passed', array_size=1000000, repetitions=10, upstream_validation=True)
    elif kind == 'rsbench':
        out, err, proof = execute([root / 'bin/rsbench', '-s', 'small', '-t', '1'], threads=1)
        assert 'Verification checksum: 879693 (Valid)' in out and 'WARNING' not in out
        proof.update(status='passed', profile='upstream Small default', upstream_checksum=879693)
    elif kind == 'epcc-openmp':
        for name, marker in (('syncbench', 'PARALLEL time'), ('schedbench', 'STATIC time'), ('taskbench', 'PARALLEL TASK time')):
            out, err, proof = execute([root / 'bin' / name, '--outer-repetitions', '2', '--test-time', '50'], threads=2, timeout=30)
            assert 'Running OpenMP benchmark version 3.0' in out and marker in out and '2 thread(s)' in out
            proof.update(status='passed', profile='upstream C_v31 selected CPU program', expected_marker=marker)
    elif kind == 'xsbench':
        out, err, proof = execute([root / 'bin/XSBench', '-s', 'small', '-t', '2'], threads=2)
        matched = re.search(r'Verification checksum:\s*(\d+)\s*\(([^)]+)\)', out)
        lookups = re.findall(r'Lookups:\s*([\d,]+)', out)
        assert matched and matched.group(1) == '941535' and matched.group(2) == 'Valid'
        assert lookups and int(lookups[-1].replace(',', '')) == 17000000
        assert re.search(r'Threads:\s*2\b', out) and 'WARNING' not in out
        proof.update(status='passed', profile='upstream Small history default', upstream_checksum=941535, lookups=17000000)
    else:
        revision = 'eb68bb8d6fc53de1f65011d4e79ff2ed0dd60f3b'
        decks = [('AllAbsorb/allAbsorb.inp', 'b767bf69c3b4ed36d4fae1b65126ae0f066e2315d95ec69bdc4f1a69f3e86e1d', 'reflect'),
                 ('AllEscape/allEscape.inp', '1219da6fc34fda1a701e54247d60b5c35ee3fd62092687ffd5b6ba9534125414', 'escape')]
        for name, digest, boundary in decks:
            deck = root / 'share/quicksilver/Examples' / name
            assert hashlib.sha256(deck.read_bytes()).hexdigest() == digest
            with tempfile.TemporaryDirectory(prefix='cpg-quicksilver-check-') as tmp:
                out, err, proof = execute([root / 'bin/qs', '-i', deck], cwd=tmp, timeout=60)
            cycles = {int(x) for x in re.findall(r'^\s*(\d+)\s+\d+\s+', out, flags=re.MULTILINE)}
            assert not err.strip() and all(x in cycles for x in range(20))
            assert 'Quicksilver Git Hash    : ' + revision in out
            for text in ('Number of MPI ranks     : 1', 'Number of OpenMP Threads: 1',
                         'Finished Consistency Check', 'nParticles: 9999', 'nSteps: 20',
                         'boundaryCondition: ' + boundary, 'Figure Of Merit'):
                assert text in out, text
            assert 'FATAL' not in out.upper() and 'ERROR' not in out.upper()
            proof.update(status='passed', deck_sha256=digest, steps=20, particles=9999,
                         scope='Original CPU serial functional workload; no independent physical oracle')
    print(json.dumps({'status': 'passed', 'resource_id': 'dataset-ref.' + kind,
                      'program_runs': results, 'official_benchmark_qualified': False,
                      'oci_qualified': False, 'physical_hardware_qualified': False}, sort_keys=True))


if __name__ == '__main__':
    main()
