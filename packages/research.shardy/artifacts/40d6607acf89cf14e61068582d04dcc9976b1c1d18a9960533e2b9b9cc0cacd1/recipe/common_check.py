#!/usr/bin/env python3
"""Run a locked OpenXLA profile using only local wheel bytes.

The package prefix is read-only. Every check gets an independent temporary
runtime beneath its output directory; that runtime is deleted even on failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys
import tempfile
import zipfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def verify_wheels(runtime, deep=False):
    lock = json.loads((runtime / 'wheel-lock.json').read_text())
    expected = {'jax': '0.8.0', 'jaxlib': '0.8.0', 'numpy': '2.3.4',
                'scipy': '1.16.3', 'ml_dtypes': '0.5.3', 'opt_einsum': '3.4.0'}
    packages = lock['packages']
    require({p['name']: p['version'] for p in packages} == expected,
            'Locked package set changed')
    require(len(packages) == len(expected), 'Duplicate or missing wheel')
    for item in packages:
        rel = PurePosixPath(item['path'])
        require(not rel.is_absolute() and '..' not in rel.parts, 'Invalid wheel path')
        f = runtime / rel
        require(f.is_file() and not f.is_symlink(), 'Wheel is not a regular local file')
        require(f.stat().st_size == item['bytes'] and digest(f) == item['sha256'],
                'Wheel integrity failure: ' + item['filename'])
        require(item['upstream_digest_verified'] is True, 'Unverified publisher digest')
        with zipfile.ZipFile(f) as z:
            if deep:
                require(z.testzip() is None, 'Wheel ZIP checksum failure')
            metadata = [n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
            require(len(metadata) == 1, 'Ambiguous wheel metadata')
            text = z.read(metadata[0]).decode()
            require('\nVersion: ' + item['version'] + '\n' in '\n' + text,
                    'Wheel metadata version mismatch')
    return lock


def main(profile, resource_id):
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--runtime-prefix', type=Path)
    args = parser.parse_args()
    prefix, out = args.prefix.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').unlink(missing_ok=True)
    runtime = (args.runtime_prefix or prefix).resolve()
    try:
        lock = verify_wheels(runtime, deep=(profile == 'runtime'))
        if profile == 'runtime':
            report = {
                'status': 'passed', 'resource_id': resource_id,
                'checks': [{'name': 'six_pinned_wheels_publisher_digest_and_zip', 'passed': True},
                           {'name': 'locked_dependency_closure', 'passed': True}],
                'evidence_files': ['runtime-lock-verification.json'],
                'functional_qualification': False,
                'scope': 'Offline dependency material, not an additional upstream resource.'}
            (out / 'runtime-lock-verification.json').write_text(json.dumps(lock, indent=2))
        else:
            require(sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12),
                    'This binary profile requires CPython 3.12')
            require(platform.system() == 'Linux' and platform.machine() in ('x86_64', 'amd64'),
                    'This binary profile requires Linux x86_64')
            libc, libc_version = platform.libc_ver()
            require(libc == 'glibc' and tuple(map(int, libc_version.split('.')[:2])) >= (2, 27),
                    'This binary profile requires glibc >= 2.27')
            with tempfile.TemporaryDirectory(prefix='openxla-check-', dir=out) as temp:
                site = Path(temp) / 'site'
                site.mkdir()
                for item in lock['packages']:
                    with zipfile.ZipFile(runtime / item['path']) as z:
                        for member in z.infolist():
                            rel = PurePosixPath(member.filename)
                            require(not rel.is_absolute() and '..' not in rel.parts,
                                    'Unsafe wheel member')
                            require((member.external_attr >> 16) & 0o170000 != 0o120000,
                                    'Symlink wheel member is unsupported')
                        z.extractall(site)
                env = os.environ.copy()
                env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
                           OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
                           TF_NUM_INTRAOP_THREADS='1', TF_NUM_INTEROP_THREADS='1',
                           JAX_PLATFORMS='cpu', JAX_ENABLE_COMPILATION_CACHE='false',
                           JAX_USE_SHARDY_PARTITIONER='true')
                env['XLA_FLAGS'] = ('--xla_cpu_multi_thread_eigen=false '
                                    '--xla_force_host_platform_device_count=' +
                                    ('2' if profile == 'shardy' else '1'))
                env.pop('PYTHONPATH', None)
                command = [sys.executable, '-B', '-I', str(prefix / 'probe.py'),
                           '--site', str(site), '--prefix', str(prefix), '--output', str(out)]
                try:
                    completed = subprocess.run(command, cwd=out, env=env, text=True,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               timeout=1800)
                except subprocess.TimeoutExpired as exc:
                    for name, value in [('execution.stdout.txt', exc.stdout),
                                        ('execution.stderr.txt', exc.stderr)]:
                        if isinstance(value, bytes):
                            value = value.decode(errors='replace')
                        (out / name).write_text(value or '')
                    raise RuntimeError('Profile exceeded 1800 seconds; partial process logs retained') from exc
                (out / 'execution.stdout.txt').write_text(completed.stdout)
                (out / 'execution.stderr.txt').write_text(completed.stderr)
                require(completed.returncode == 0,
                        'Profile exited ' + str(completed.returncode) + ': ' + completed.stderr[-2000:])
                report = json.loads((out / 'probe-result.json').read_text())
                require(report.get('status') == 'passed', 'Probe did not pass')
                require(report['checks'] and all(x.get('passed') is True for x in report['checks']),
                        'A semantic check failed')
                report['resource_id'] = resource_id
                report['runtime'] = {'python': platform.python_version(), 'glibc': libc_version,
                                     'wheel_lock_sha256': digest(runtime / 'wheel-lock.json'),
                                     'isolated_runtime': True, 'runtime_removed_after_check': True}
                report['evidence_files'] += ['execution.stdout.txt', 'execution.stderr.txt',
                                            'probe-result.json']
        report['evidence_sha256'] = {rel: digest(out / rel) for rel in report['evidence_files']}
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('CPG_CHECK_PASS ' + resource_id)
    except Exception as exc:
        (out / 'result.json').write_text(json.dumps({
            'status': 'failed', 'resource_id': resource_id, 'error': str(exc),
            'checks': [], 'evidence_files': []}, ensure_ascii=False, indent=2))
        raise
