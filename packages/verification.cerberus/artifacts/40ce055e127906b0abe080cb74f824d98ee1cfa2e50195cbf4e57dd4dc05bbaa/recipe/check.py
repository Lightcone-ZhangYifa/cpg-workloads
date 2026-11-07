"""Check the official examples under one explicitly fixed C semantics model."""
import json
from pathlib import Path
import subprocess
import sys

prefix = Path(sys.argv[1]).resolve()
work = Path.cwd() / 'functional-evidence'
work.mkdir(parents=True, exist_ok=True)
checks = []
cases = [('0003-return_arith.c', 0, 'Specified(3)'),
         ('0013-incr_pointer.c', 0, 'Specified(0)'),
         ('0020-end_of_lifetime.undef.c', 1, 'UB011_use_indeterminate_automatic_object')]
for name, expected, token in cases:
    source = work / name
    source.write_bytes((prefix / 'share/fixtures' / name).read_bytes())
    argv = [str(prefix / 'bin/cerberus'), '--exec', '--batch', '--mode=exhaustive', '--iso',
            '--impl=gcc_4.9.0_x86_64-apple-darwin10.8.0', str(source)]
    result = subprocess.run(argv, cwd=work, capture_output=True, text=True, timeout=150)
    row = {'case': name, 'argv': argv, 'returncode': result.returncode,
           'stdout': result.stdout, 'stderr': result.stderr}
    checks.append(row)
    (work / (name + '.stdout.log')).write_text(result.stdout)
    (work / (name + '.stderr.log')).write_text(result.stderr)
    (work / (name + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    if result.returncode != expected or token not in result.stdout:
        raise RuntimeError('Cerberus semantic result mismatch: ' + json.dumps(row))
    if ('Undefined {' if expected else 'Defined {') not in result.stdout:
        raise RuntimeError('Cerberus did not report the intended defined/undefined outcome: ' + json.dumps(row))
print(json.dumps({'status': 'passed', 'resource': 'verification.cerberus', 'checks': checks}))
