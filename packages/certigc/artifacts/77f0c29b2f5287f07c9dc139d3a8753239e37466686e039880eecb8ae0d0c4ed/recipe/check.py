#!/usr/bin/env python3
"""Independent-prefix CertiGC check with no historical process dependency."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import os
import resource
import signal
import subprocess
import sys
import tempfile

if not __debug__:
    raise RuntimeError('Installed verification gates may not be optimized away')

HELPER_SHA = '013d5f2049cc3b59eee7f26e836b53a06f34cd0ea22e5469ec50fcccd6f780cb'
LEASE_KEYS = (
    'CPG_CERTIGC_PAUSE_LEASE', 'CPG_CERTIGC_PAUSE_LEASE_SHA256',
    'CPG_CERTIGC_RETAINED_PROOFS_LEASE', 'CPG_CERTIGC_RETAINED_PROOFS_LEASE_SHA256',
    'CPG_CERTIGC_ORPHAN_RETENTION_LEASE', 'CPG_CERTIGC_ORPHAN_RETENTION_LEASE_SHA256',
)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def local(root, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or not parts.parts:
        raise RuntimeError('Installed manifest contains an escaping path')
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('Installed input escapes this independent prefix')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args()
    prefix = Path(args.prefix).resolve()
    support = prefix / 'checker'
    manifest = read(prefix / 'checker-manifest.json')
    known = {}
    for row in manifest['files']:
        path = local(support, row['path'])
        if row['path'] in known or not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise RuntimeError('Independent checker file or manifest identity differs')
        known[row['path']] = row
    proof = read(prefix / 'proof-acceptance.json')
    if proof['status'] != 'passed' or proof['target'] != 'x86_64-linux' or proof['source_build_directory'] != 'proof-build-o10-s16' or proof['compiled_modules'] != 34 or proof['source_files_unchanged'] != 106:
        raise RuntimeError('The selected original source and independent audit have not been accepted')
    if digest(prefix / 'checker-manifest.json') != proof['checker_manifest_sha256'] or digest(prefix / 'compiled-manifest.json') != proof['compiled_manifest_sha256']:
        raise RuntimeError('Accepted checker/compiled manifests changed')
    compiled = read(prefix / 'compiled-manifest.json')
    if len(compiled['files']) != 34 or len({r['path'] for r in compiled['files']}) != 34:
        raise RuntimeError('The selected compiled closure is not exactly 34 distinct modules')
    for row in compiled['files']:
        path = local(prefix / 'compiled', row['path'])
        if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise RuntimeError('An independently installed proof object differs')
    target = prefix / 'compiled/src/certigc/theories/CertiGC/vst/verif/verif_garbage_collect.vo'
    if digest(target) != proof['target_vo_sha256']:
        raise RuntimeError('The installed target differs from its actual source/audit acceptance')
    recovery_binding = proof['orphan_object_recovery']
    recovery_path = prefix / 'evidence/orphan-object-recovery/acceptance.json'
    if digest(recovery_path) != recovery_binding['sha256']:
        raise RuntimeError('The retained independent spatial-object acceptance changed')
    recovery = read(recovery_path)
    if recovery['status'] != 'independently-kernel-checked' or recovery['original_source_returncode'] is not None or recovery['independent_kernel_returncode'] != 0:
        raise RuntimeError('Unknown original source exit must not be invented as successful')
    if recovery['object_relative_to_build'] != recovery_binding['object'] or recovery['recovered_object_sha256'] != recovery_binding['object_sha256'] or digest(local(prefix / 'compiled', recovery_binding['object'])) != recovery_binding['object_sha256']:
        raise RuntimeError('Recovered spatial source object differs')
    if digest(prefix / 'evidence/orphan-object-recovery/step.json') != recovery['step']['sha256']:
        raise RuntimeError('Independent spatial check receipt changed')
    profile = manifest['runtime_profile']
    if profile['id'] != 'author-amd64-with-official-gperftools-memfs' or proof['runtime_profile']['id'] != profile['id'] or profile['helper_sha256'] != HELPER_SHA or proof['runtime_profile']['runtime_helper_sha256'] != HELPER_SHA:
        raise RuntimeError('The installed portable observer lacks the actual audit identity')
    if profile['historical_process_dependencies'] or profile['installed_external_guard'] is not None or profile['guard_path'] is not None or profile['guard_sha256'] is not None or profile['cleared_lease_environment_families'] != 3:
        raise RuntimeError('An installed prefix may not depend on historical process/lease state')
    if profile['fallback_after_registration'] or not profile['ordinary_private_pool_required'] or profile['pool_limit_mib'] != 1024:
        raise RuntimeError('Installed bounded allocator profile differs')
    qualified = proof['steps'][:2]
    if [r['name'] for r in qualified] != ['target-assumptions', 'negative-target'] or [r['returncode'] for r in qualified] != [0, 1] or hashlib.sha256(json.dumps(qualified, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != profile['helper_qualification_records_sha256']:
        raise RuntimeError('Actual target/architecture qualification for this helper is missing')
    if any(not r['passed'] or not r['child_reaped'] or r['controller_signals'] or not r['actual_shared_file_pool_mapping'] or r['runtime_observer_sha256'] != HELPER_SHA for r in qualified):
        raise RuntimeError('The target controls did not complete normally with this exact observer')
    helper = local(support, profile['helper_path'])
    allocator = local(support, profile['allocator_path'])
    if profile['helper_path'] not in known or profile['allocator_path'] not in known or digest(helper) != HELPER_SHA or digest(allocator) != profile['allocator_sha256']:
        raise RuntimeError('Prefix-local allocator/helper bytes are not in the accepted independent closure')
    steps = []
    clean_env = dict(os.environ)
    clean_env.pop('LD_PRELOAD', None)
    removed = [key for key in LEASE_KEYS if key in clean_env]
    for key in LEASE_KEYS:
        clean_env.pop(key, None)

    def c_control(name, command, expected):
        completed = subprocess.run(command, cwd=prefix, env=clean_env, text=True, capture_output=True,
            timeout=300, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
        row = {'name': name, 'command': command, 'cwd': str(prefix), 'returncode': completed.returncode,
               'expected': [expected], 'passed': completed.returncode == expected,
               'stdout': completed.stdout, 'stderr': completed.stderr}
        steps.append(row)
        if not row['passed']:
            print(json.dumps({'status': 'failed', 'steps': steps}, ensure_ascii=False))
            raise SystemExit(1)
        return completed

    binary = prefix / 'bin/gc-smoke'
    runtime = read(prefix / 'evidence/runtime-acceptance.json')
    if not runtime['all_passed'] or runtime['target'] != 'x86_64-linux' or not runtime['compiler_target'].startswith('x86_64-') or binary.is_symlink() or binary.stat().st_nlink != 1 or binary.stat().st_size != runtime['binary_bytes'] or digest(binary) != runtime['binary_sha256']:
        raise RuntimeError('The installed real GC binary differs from its locked runtime evidence')
    result = c_control('gc-roots-sharing-reclamation', [str(binary)], 0)
    metrics = json.loads(result.stdout)
    if metrics['collections'] != 2 or metrics['copied_live_words'] != 6 or metrics['restored_nursery_words'] != 65536 or metrics['root_value'] != 12345 or metrics['shared_child_preserved'] is not True:
        raise RuntimeError('Actual allocation, live roots, sharing or reclamation differs')
    result = c_control('gc-invalid-root-rejected', [str(binary), 'invalid-root'], -signal.SIGABRT)
    if 'roots[i] < MAX_ARGS' not in result.stderr:
        raise RuntimeError('The invalid-root negative control failed for an unexpected reason')
    result = c_control('gc-oversized-request-rejected', [str(binary), 'oversized-request'], 1)
    if "Nursery is too small for function's num_allocs" not in result.stderr:
        raise RuntimeError('The oversize negative control failed for an unexpected reason')
    sys.dont_write_bytecode = True
    module_spec = importlib.util.spec_from_file_location('cpg_certigc_prefix_runtime', helper)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if module.GC != profile['ocamlrunparam'] or tuple(module.LEASE_ENVIRONMENT_KEYS) != LEASE_KEYS:
        raise RuntimeError('The exact portable helper runtime/environment policy differs')
    q = []
    for row in read(prefix / 'proof-paths.json'):
        q.extend(['-Q', str(local(prefix / 'compiled', row['path'])), row['logical']])
    temporary_parent = os.environ.get('CPG_CHECK_TMPDIR')
    if temporary_parent:
        Path(temporary_parent).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cpg-certigc-proof-', dir=temporary_parent) as td:
        work = Path(td)
        pool = work / 'pool'
        env, allocator = module.environment(prefix, pool, profile['pool_limit_mib'], allocator, toolchain=support)
        if any(key in env for key in LEASE_KEYS):
            raise RuntimeError('No historical lease variable may reach the installed native checker')
        command = [str(support / 'bin/coqchk'), '-coqlib', str(support / 'lib/coq'), *q,
                   '-norec', 'CertiGC.vst.verif.verif_garbage_collect', '-o', '-m', '-silent']
        row = module.run(command, env, work, work / 'selected-kernel', support / 'bin/coqchk', allocator, pool,
                         timeout=1500, external_guard=None)
        cleanup = read(work / 'selected-kernel.cleanup.json')
        ok = row['returncode'] == 0 and not row['timed_out'] and row['child_reaped'] and not row['controller_signals'] and row['actual_shared_file_pool_mapping'] and row['pause_lease_error'] is None and row['pause_lease_sha256'] is None and row['pause_lease_checks'] == 0
        ok = ok and cleanup['actual_returncode'] == 0 and cleanup['child_reaped'] and not cleanup['ownership_lost'] and cleanup['stop_reason'] is None and not cleanup['actions'] and not cleanup['controller_signals'] and not cleanup['original_kernel_signals']
        identities = row['mapping_identities']
        ok = ok and any(x['path'] == command[0] and x.get('sha256') == known['bin/coqchk']['sha256'] for x in identities)
        ok = ok and any(x['path'] == str(allocator) and x.get('sha256') == profile['allocator_sha256'] for x in identities)
        row.update(name='kernel-check-selected-gc-module', expected=[0], passed=ok,
            cleanup_receipt=cleanup, runtime_observer_sha256=HELPER_SHA,
            historical_process_dependencies=False, installed_external_guard=None,
            stdout=(work / 'selected-kernel.stdout').read_text(), stderr=(work / 'selected-kernel.stderr').read_text())
        steps.append(row)
        if not ok:
            print(json.dumps({'status': 'failed', 'steps': steps}, ensure_ascii=False))
            raise SystemExit(1)
    print(json.dumps({'status': 'passed', 'kind': 'functional', 'target': 'x86_64-linux',
        'support_files_checked': len(manifest['files']), 'metrics': metrics, 'steps': steps,
        'historical_process_dependencies': False, 'cleared_lease_environment_families': 3,
        'removed_inherited_lease_keys': removed,
        'scope': 'Bounded real GC execution and independent-prefix coqchk -norec of the source-replayed selected GC module. Dependencies remain byte-locked and loaded without recursive rechecking; upstream admissions remain explicit. No general JIT, barrier/reset_heap, performance or axiom-free-system claim.'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
