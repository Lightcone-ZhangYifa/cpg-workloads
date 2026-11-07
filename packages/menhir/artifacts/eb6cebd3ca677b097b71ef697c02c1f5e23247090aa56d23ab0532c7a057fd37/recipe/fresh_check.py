#!/usr/bin/env python3
"""Give each original-Manager check a fresh output subtree, preserving old evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--parent', type=Path, required=True)
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
command = args.command[1:] if args.command[:1] == ['--'] else args.command
parent = args.parent.resolve()
fresh = Path(tempfile.mkdtemp(prefix='functional-', dir=parent))
for i, value in enumerate(command):
    if i and command[i - 1] in ('--work-dir', '--evidence-dir', '--build', '--evidence'):
        command[i] = str(fresh / Path(value).name)
print(json.dumps({'functional_attempt': str(fresh), 'argv': command}), flush=True)
raise SystemExit(subprocess.call(command))
