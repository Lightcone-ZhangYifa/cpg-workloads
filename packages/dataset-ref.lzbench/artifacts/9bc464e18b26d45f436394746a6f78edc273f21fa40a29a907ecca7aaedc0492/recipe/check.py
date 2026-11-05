#!/usr/bin/env python3
"""Independent lzbench functional smoke using upstream decompressed-byte verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    binary = args.prefix / 'bin' / 'lzbench'
    if not binary.is_file():
        raise RuntimeError(f'Missing executable: {binary}')
    with tempfile.TemporaryDirectory(prefix='lzbench-cpg-check-') as tmp:
        directory = Path(tmp)
        texts = {
            'structured.txt': (b'CompilerPlayground exact compressed-source check\n' * 4600),
            'mixed.bin': b''.join(hashlib.sha256(f'CPG-lzbench-{i:08d}'.encode()).digest()
                                for i in range(2048)),
        }
        for name, data in texts.items():
            (directory / name).write_bytes(data)
        argv = [str(binary), '-ezlib,1/lz4', '-t0,0', '-i1,1',
                str(directory / 'structured.txt'), str(directory / 'mixed.bin')]
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=90, check=False)
        lines = completed.stdout.splitlines()
        matches = {name: {codec: any(line.lower().startswith(codec + ' ') and name in line
                                         for line in lines) for codec in ('zlib', 'lz4')}
                   for name in texts}
        if completed.returncode or 'ERROR' in completed.stdout or 'ERROR' in completed.stderr \
                or not all(all(results.values()) for results in matches.values()):
            raise RuntimeError(json.dumps({'status': 'failed', 'returncode': completed.returncode,
                                           'matches': matches, 'stdout_tail': completed.stdout[-4000:],
                                           'stderr_tail': completed.stderr[-1000:]}))
        version = subprocess.run([str(binary), '-V'], capture_output=True, text=True,
                                 timeout=10, check=False)
        if version.returncode or 'lzbench' not in (version.stdout + version.stderr):
            raise RuntimeError('Version query unexpectedly failed')
        print(json.dumps({'status': 'passed', 'checks': 'roundtrip compares full decompressed bytes in upstream lzbench.cpp',
                          'two_codecs': ['zlib', 'lz4'], 'two_distinct_inputs': True,
                          'total_input_bytes': sum(map(len, texts.values())),
                          'match_count': sum(map(len, matches.values())),
                          'version': (version.stdout + version.stderr).strip()[:200]}))


if __name__ == '__main__':
    main()
