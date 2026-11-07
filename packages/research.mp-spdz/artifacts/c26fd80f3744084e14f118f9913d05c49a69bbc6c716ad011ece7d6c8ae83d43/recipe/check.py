#!/usr/bin/env python3
"""Compile and execute the unmodified upstream two-party MASCOT tutorial."""
import argparse
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

PRIME = 170141183460469231731687303715884105727  # Mersenne prime 2**127 - 1

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--full-tutorial', action='store_true', help='Run the unchanged upstream tutorial; default is a small input-sensitive arithmetic profile')
    parser.add_argument('--payload-lock-sha256', help='Exact lock identity bound by the native CPG package definition')
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    output_base = args.output.resolve()
    output_base.mkdir(parents=True, exist_ok=True)
    output = output_base / ('check-' + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / 'result.json'
    if result_path.exists():
        result_path.unlink()
    work = output / 'run'
    require(not work.exists(), 'Use a new output directory for each independent run')
    work.mkdir()
    lock_file = prefix / 'PAYLOAD_LOCK.json'
    if args.payload_lock_sha256:
        require(digest(lock_file) == args.payload_lock_sha256, 'Payload lock identity differs from native package declaration')
    expected = json.loads(lock_file.read_text())
    for row in expected:
        path = prefix / row['path']
        require(path.is_file() and path.stat().st_size == row['bytes'] and digest(path) == row['sha256'], 'Payload changed: ' + row['path'])
    flags = set(Path('/proc/cpuinfo').read_text().split())
    require({'adx', 'avx2', 'bmi2', 'aes', 'pclmulqdq'} <= flags, 'Official Linux-adx binary requires ADX/AVX2/BMI2/AES/PCLMULQDQ')
    for directory in ['Compiler', 'Programs']:
        shutil.copytree(prefix / directory, work / directory, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(prefix / 'compile.py', work / 'compile.py')
    (work / 'Player-Data').mkdir()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OMP_NUM_THREADS='1')
    env.pop('PYTHONPATH', None)
    env['LD_PRELOAD'] = str(prefix / 'libloopback_guard.so')
    commands = []
    def run(argv, label, expected_code=0, timeout=90):
        started = time.monotonic()
        proc = subprocess.run(argv, cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
        (output / (label + '.stdout')).write_text(proc.stdout)
        (output / (label + '.stderr')).write_text(proc.stderr)
        commands.append({'argv': argv, 'label': label, 'returncode': proc.returncode, 'duration_seconds': time.monotonic() - started})
        require(proc.returncode == expected_code, label + ' exit code ' + str(proc.returncode) + ': ' + proc.stderr[-1000:])
        return proc

    probe = """import errno,json,socket
s=socket.socket();s.bind(('0.0.0.0',0));bound=s.getsockname()[0];s.close()
t=socket.socket();t.settimeout(.2)
try:
 t.connect(('192.0.2.1',9));raise RuntimeError('external connection accepted')
except OSError as e:
 if e.errno!=errno.EACCES:raise RuntimeError('transport policy did not reject before network: '+str(e))
finally:t.close()
if bound!='127.0.0.1':raise RuntimeError('listener did not bind loopback')
print(json.dumps({'bind_any_rewritten_to':bound,'external_connect_errno':errno.EACCES}))
"""
    policy = run([sys.executable, '-S', '-B', '-c', probe], 'loopback-policy')
    program = 'tutorial' if args.full_tutorial else 'cpg_smoke'
    run([sys.executable, '-S', '-B', 'compile.py', '-E', 'mascot', '-F', '64', '-P', str(PRIME), program], 'compile-' + program, timeout=600)
    bytecode_files = sorted((work / 'Programs/Bytecode').glob('*'))
    schedule_files = sorted((work / 'Programs/Schedules').glob('*'))
    require(bool(bytecode_files) and bool(schedule_files), 'Compiler emitted no program')
    compiled_files = [{'path': p.relative_to(work).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in bytecode_files + schedule_files]

    # Ephemeral self-signed certificates are test inputs, never persisted as credentials.
    for i in range(2):
        run(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-x509', '-days', '1', '-out', 'Player-Data/P%d.pem' % i, '-keyout', 'Player-Data/P%d.key' % i, '-subj', '/CN=P%d' % i], 'certificate-%d' % i)
    run(['openssl', 'rehash', 'Player-Data'], 'certificate-rehash')
    cases = ([([1,2,3,4], [1,2,3,4]), ([7,1,2,3], [9,4,5,6])] if args.full_tutorial else
             [([2,3,5], [7,11,13]), ([-7,0,4], [6,2,-3]), ([0,1,-1], [5,-4,9])])
    checked_cases = []
    all_processes = []
    try:
        for case_index, inputs in enumerate(cases):
            for player, values in enumerate(inputs):
                (work / ('Player-Data/Input-P%d-0' % player)).write_text(' '.join(map(str, values)) + '\n')
            # Choose a currently unused adjacent port pair. This is a local test allocation.
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            processes = []
            for player in range(2):
                argv = [str(prefix / 'bin/mascot-party.x'), '-p', str(player), '-N', '2', '-h', '127.0.0.1', '-pn', str(port), '-P', str(PRIME), '-lgp', '127', '-S', '40', '-b', '128', '-e', program]
                proc = subprocess.Popen(argv, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                processes.append((player, argv, proc))
                all_processes.append(proc)
            outputs = []
            for player, argv, proc in processes:
                stdout, stderr = proc.communicate(timeout=240)
                label = 'case-%d-player-%d' % (case_index, player)
                (output / (label + '.stdout')).write_text(stdout)
                (output / (label + '.stderr')).write_text(stderr)
                commands.append({'argv': argv, 'label': label, 'returncode': proc.returncode})
                require(proc.returncode == 0, label + ' failed: ' + stderr[-2000:])
                outputs.append(stdout + '\n' + stderr)
            transcript = outputs[0]
            if not args.full_tutorial:
                observed = [int(x) for x in re.search(r'CPG: ([+-]?\d+) ([+-]?\d+) ([+-]?\d+) ([+-]?\d+)', transcript).groups()]
                left, right = inputs
                oracle = [left[0]+right[0], left[0]*right[0], left[0]-right[0], sum(x*y for x,y in zip(left,right))]
                require(observed == oracle, 'Independent exact integer arithmetic mismatch')
                checked_cases.append({'synthetic_inputs': inputs, 'observed': observed, 'independent_reference': oracle, 'party_exit_codes': [p.returncode for _,_,p in processes], 'port_base': port})
                continue
            comparisons = re.findall(r'expected ([+-]?[\d.eE]+), got ([+-]?[\d.eE]+)', transcript)
            require(len(comparisons) == 25, 'Unexpected number of official tutorial checks: ' + str(len(comparisons)))
            for want, got in comparisons:
                w, g = float(want), float(got)
                require(math.isfinite(g) and math.isclose(w, g, rel_tol=1e-3, abs_tol=2e-3), 'Tutorial mismatch: ' + want + ' vs ' + got)
            for player in range(2):
                require('got %d from player %d' % (inputs[player][0], player) in transcript, 'Party input mismatch')
            average = float(re.search(r'weighted average: ([+-]?[\d.eE]+)', transcript).group(1))
            expected_average = sum(x*y for x,y in zip(inputs[0][1:], inputs[1][1:])) / sum(inputs[0][1:])
            require(math.isclose(average, expected_average, rel_tol=1e-3, abs_tol=2e-3), 'Independent weighted average mismatch')
            checked_cases.append({'synthetic_inputs': inputs, 'official_comparisons': len(comparisons), 'weighted_average': average, 'independent_reference': expected_average, 'party_exit_codes': [p.returncode for _,_,p in processes], 'port_base': port})
    finally:
        for proc in all_processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        # Test private keys are not part of evidence or the installed resource.
        for private_key in (work / 'Player-Data').rglob('*'):
            if private_key.is_file() and (private_key.suffix == '.key' or 'Secrets' in private_key.name or private_key.name.startswith('MAC-Keys')):
                private_key.unlink()
    (work / 'Programs/Source/cpg_invalid.mpc').write_text('def invalid(:\n')
    proc = subprocess.run([sys.executable, '-S', '-B', 'compile.py', '-E', 'mascot', 'cpg_invalid'], cwd=work, env=env, capture_output=True, text=True, timeout=60)
    (output / 'compile-invalid.stdout').write_text(proc.stdout)
    (output / 'compile-invalid.stderr').write_text(proc.stderr)
    require(proc.returncode != 0 and 'SyntaxError' in proc.stderr, 'Invalid source not rejected by compiler')
    require(not (work / 'Programs/Schedules/cpg_invalid.sch').exists(), 'Failed compilation left runnable schedule')
    commands.append({'argv': [sys.executable, '-S', '-B', 'compile.py', '-E', 'mascot', 'cpg_invalid'], 'label': 'compile-invalid', 'returncode': proc.returncode, 'expected_failure': True})
    result = {'status':'passed', 'resource':'research.mp-spdz', 'version':'0.4.4', 'protocol':'MASCOT', 'security_model':'malicious/dishonest-majority; local functionality only, not a security proof', 'parties':2, 'prime_modulus':str(PRIME), 'modulus_bits':127, 'integer_bits':64, 'statistical_security_bits':40, 'preprocessing_batch_size':128, 'encrypted_channels':True, 'compiler_profile':'official unchanged tutorial.mpc' if args.full_tutorial else 'CPG-authored small integer program using upstream compiler and MASCOT runtime', 'cases':checked_cases, 'compiled_files':compiled_files, 'negative_tests':{'invalid_source_rejected':True, 'external_libc_connect_rejected':True, 'wildcard_bind_rewritten_to_loopback':True}, 'transport_policy':json.loads(policy.stdout), 'transport_policy_limit':'LD_PRELOAD policy for a trusted dynamic binary; not an adversarial network sandbox; netns unavailable', 'commands':commands, 'qualified':{'material':True,'functional':True,'source_build':False,'hardware':False,'cryptographic_security_proof':False,'official_full_suite':False}}
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    pointer = output_base / ('last-result-' + uuid.uuid4().hex + '.tmp')
    pointer.write_text(json.dumps({'status': 'passed', 'result_path': str(result_path), 'result_sha256': digest(result_path)}, indent=2) + '\n')
    pointer.replace(output_base / 'last-result.json')
    print('PASS: mp-spdz MASCOT ' + program + ', 2 parties, ' + str(len(cases)) + ' synthetic input cases')
    print('RESULT: ' + str(result_path))

if __name__ == '__main__':
    main()
