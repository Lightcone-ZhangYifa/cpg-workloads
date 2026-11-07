"""Run the installed verifier's bounded positive and negative profile.

All generated files go into a fresh output directory, outside the prefix.
The verifier's exit status alone is not enough: diagnostics must also match.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prefix', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    prefix = args.prefix.resolve(strict=True)
    config = json.loads((prefix / 'share/cpg/profile.json').read_text())
    output_root = args.output.absolute()
    if output_root.is_relative_to(prefix):
        raise ValueError('The check output must be outside the installation')
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=config['resource'] + '-', dir=output_root))
    fixtures = prefix / 'share/cpg/fixtures'
    env = os.environ.copy()
    env.update({'LC_ALL': 'C', 'TZ': 'UTC', 'PYTHONDONTWRITEBYTECODE': '1'})
    rows = []
    for case in config['cases']:
        work = output / case['name']
        work.mkdir()
        source = work / case['file']
        shutil.copy2(fixtures / case['file'], source)
        if config['resource'] == 'viper':
            cmd = ['java', '-XX:ActiveProcessorCount=2', '-XX:+UseSerialGC',
                   '-Xms32m', '-Xmx256m', '-XX:MaxMetaspaceSize=192m',
                   '-cp', str(prefix / 'tool/backends/viperserver.jar'),
                   'viper.silicon.SiliconRunner', '--z3Exe',
                   str(prefix / 'tool/z3/bin/z3'), '--numberOfParallelVerifiers', '1',
                   '--timeout', '120', '--disableCaches', '--logLevel', 'WARN',
                   '--enableTempDirectory', '--tempDirectory', str(work / 'smt'), str(source)]
        elif config['resource'] == 'verifast':
            cmd = [str(prefix / 'tool/bin/verifast'), '-target', 'Linux64',
                   '-prover', 'Z3v4.5', '-fno-strict-aliasing', '-c', str(source)]
        else:
            raise ValueError('Unknown verifier profile')
        started = time.monotonic()
        proc = subprocess.run(cmd, cwd=work, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=180)
        (work / 'stdout.txt').write_bytes(proc.stdout)
        (work / 'stderr.txt').write_bytes(proc.stderr)
        text = (proc.stdout + proc.stderr).decode('utf-8', 'replace')
        ok = proc.returncode == case['returncode'] and re.search(case['diagnostic'], text) is not None
        row = {'name': case['name'], 'command': cmd, 'returncode': proc.returncode,
               'expected_returncode': case['returncode'], 'diagnostic': case['diagnostic'],
               'elapsed_seconds': time.monotonic() - started, 'passed': ok,
               'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'stdout_sha256': hashlib.sha256(proc.stdout).hexdigest(),
               'stderr_sha256': hashlib.sha256(proc.stderr).hexdigest()}
        (work / 'run.json').write_text(json.dumps(row, indent=2) + '\n')
        rows.append(row)
    result = {'resource': config['resource'], 'passed': all(r['passed'] for r in rows),
              'case_count': len(rows), 'cases': rows, 'scope': config['scope'],
              'verification_options': config['verification_options']}
    (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'resource': config['resource'], 'passed': result['passed'],
                      'case_count': len(rows), 'evidence': str(output)}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
