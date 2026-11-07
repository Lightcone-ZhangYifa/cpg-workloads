"""Verify the fixed official array example and its boundary mutation."""
import json
from pathlib import Path
import subprocess
import sys

prefix = Path(sys.argv[1]).resolve()
work = Path.cwd() / 'functional-evidence'
work.mkdir(parents=True, exist_ok=True)
checks = []
for name, expected in [('get_from_array', 0), ('get_from_array_bound_violation', 1)]:
    source = work / (name + '.c')
    source.write_bytes((prefix / 'share/fixtures' / (name + '.c')).read_bytes())
    out = work / (name + '-state')
    out.mkdir(exist_ok=True)
    argv = [str(prefix / 'bin/cn'), 'verify', '--json', '--only=set_a_pointer', '--incremental-solver-timeout=10000',
            '--solver-path=' + str(prefix / 'bin/z3'), '--output-dir=' + str(out), str(source)]
    result = subprocess.run(argv, cwd=work, text=True, capture_output=True, timeout=120)
    row = {'case': name, 'argv': argv, 'returncode': result.returncode,
           'stdout': result.stdout, 'stderr': result.stderr}
    checks.append(row)
    (work / (name + '.stdout.log')).write_text(result.stdout)
    (work / (name + '.stderr.log')).write_text(result.stderr)
    (work / (name + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    if result.returncode != expected:
        raise RuntimeError('Unexpected CN exit status: ' + json.dumps(row))
    if expected == 0:
        if 'set_a_pointer -- pass' not in result.stdout:
            raise RuntimeError('CN did not verify the specified array function: ' + json.dumps(row))
    else:
        if ('set_a_pointer -- fail' not in result.stdout or
                'Missing resource for writing' not in result.stderr or
                'W<signed int>(p)' not in result.stderr):
            raise RuntimeError('CN did not diagnose the intended boundary violation: ' + json.dumps(row))
print(json.dumps({'status': 'passed', 'resource': 'verification.cn', 'checks': checks}, ensure_ascii=False))
