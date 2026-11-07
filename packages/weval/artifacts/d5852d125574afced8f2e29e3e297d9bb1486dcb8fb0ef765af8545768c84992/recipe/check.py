#!/usr/bin/env python3
"""Run the installed weval example against exact CPG runtime dependencies."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix', type=Path, required=True)
    p.add_argument('--wasmtime-prefix', type=Path, required=True)
    p.add_argument('--wasm-tools-prefix', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='weval-', dir=a.output))
    argv = [sys.executable, str(a.prefix / 'share/weval/offline.py'), 'check',
            '--prefix', str(a.prefix), '--work-dir', str(work / 'run'),
            '--wasmtime', str(a.wasmtime_prefix / 'bin/wasmtime'),
            '--wasm-tools', str(a.wasm_tools_prefix / 'bin/wasm-tools')]
    proc = subprocess.run(argv, text=True, capture_output=True, timeout=240)
    (work / 'stdout.log').write_text(proc.stdout)
    (work / 'stderr.log').write_text(proc.stderr)
    if proc.returncode:
        raise RuntimeError('weval check failed; logs retained in ' + str(work))
    value = json.loads((work / 'run/validation.json').read_text())
    if value.get('status') != 'passed' or value.get('expected_steps') != 70000006:
        raise RuntimeError('weval oracle result mismatch')
    print(json.dumps(value))


if __name__ == '__main__':
    main()
