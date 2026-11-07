#!/usr/bin/env python3
"""Repeat finite Wasm transformation checks using a pinned independent runtime."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resource', choices=['binaryen', 'waffle'], required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--reference-prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=args.resource + '-', dir=args.output))
    records = []

    def run(name, argv):
        argv = list(map(str, argv))
        process = subprocess.run(argv, text=True, capture_output=True, timeout=180)
        (work / (name + '.stdout.log')).write_text(process.stdout)
        (work / (name + '.stderr.log')).write_text(process.stderr)
        records.append({'name': name, 'argv': argv, 'returncode': process.returncode})
        if process.returncode:
            raise RuntimeError(name + ' failed; logs retained in ' + str(work))
        return process.stdout

    run('installed-resource', [sys.executable,
        args.prefix / 'share/cpg-worker013/check.py', args.prefix])
    before = args.prefix / 'share/cpg-worker013/fixtures/math.wasm'
    after = work / 'after.wasm'
    if args.resource == 'binaryen':
        run('optimize', [args.prefix / 'bin/wasm-opt', '-O2', before, '-o', after])
    else:
        run('ssa-roundtrip', [args.prefix / 'bin/cpg-waffle-check', before, after, work / 'ssa.txt'])
    reference = args.reference_prefix / 'bin/cpg-wasmtime-check'
    a = json.loads(run('reference-before', [reference, 'math', before]))
    b = json.loads(run('reference-after', [reference, 'math', after]))
    expected = {'numeric_cases': 225, 'memory_cases': 32, 'trap_cases': 1,
                'checksum': 357120112336}
    if a != expected or b != expected:
        raise RuntimeError('Independent runtime oracle mismatch')
    result = {'status': 'passed', 'resource_id': args.resource,
              'reference_resource_id': 'wasmtime-cranelift',
              'assertions': expected, 'commands': records,
              'scope': 'Finite declared numeric, memory and trap fixtures; not a general equivalence proof.'}
    (work / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
