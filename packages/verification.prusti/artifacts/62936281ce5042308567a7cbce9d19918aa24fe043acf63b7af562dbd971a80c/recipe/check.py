"""Check a verified compressed Prusti runtime in a fresh independent directory.

The original CPG verifier checks every inner member and the original ELF checker
checks all expanded binaries before the original five-case functional profile.
Only a regenerable runtime expansion is removed; all diagnostic evidence stays.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import traceback
import uuid
from compiler_playground.packages.archive import verify_package
from compiler_playground.packages.compatibility import check_binary_runtime
from compiler_playground.packages.manager import current_target


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve(strict=True)
    output = args.output.resolve()
    require(not output.is_relative_to(prefix), 'Evidence must be outside the installation')
    output.mkdir(parents=True, exist_ok=True)
    lock = json.loads((prefix / 'capsule-lock.json').read_text())
    record_file = output / ('capsule-' + uuid.uuid4().hex + '.json')
    record = {'status': 'running', 'original_manager_modified': False,
              'capsule': lock, 'actual_target': current_target(),
              'native_runtime_compatibility': [], 'expanded_runtime_removed': False}
    save(record_file, record)
    try:
        with tempfile.TemporaryDirectory(prefix='prusti-runtime-', dir=output.parent) as temporary:
            runtime = Path(temporary) / 'tree'
            verified = verify_package(prefix / 'runtime.cpgpkg.tar.gz', extract=runtime,
                                      expected_sha256=lock['sha256'], expected_bytes=lock['bytes'])
            manifest = (prefix / 'runtime-manifest.json').read_bytes()
            require(hashlib.sha256(manifest).hexdigest() == lock['manifest_file_sha256'],
                    'Retained runtime manifest copy changed')
            require(json.loads(manifest) == verified['manifest'], 'Inner CPG manifest differs')
            require(verified['manifest']['package']['id'] == lock['id'] and
                    verified['manifest']['package']['version'] == lock['version'], 'Wrong capsule identity')
            record['capsule_integrity'] = 'verified_by_original_cpg'
            payload = runtime / 'payload'
            runtime_environment = {'LD_LIBRARY_PATH': ':'.join(str(payload / p) for p in
                                   ['rust/lib', 'jre/lib', 'jre/lib/server'])}
            record['declared_runtime_environment'] = runtime_environment
            try:
                check_binary_runtime(payload, actual_target=record['actual_target'],
                                     environment=runtime_environment,
                                     evidence=record['native_runtime_compatibility'])
            finally:
                save(record_file, record)
            require(len(record['native_runtime_compatibility']) > 0, 'No actual ELF binaries were checked')
            record['native_runtime_compatibility_status'] = 'passed'
            original_argv = sys.argv[:]
            old_environment = {key: value for key, value in os.environ.items() if key.startswith('LD_')}
            record['ignored_ambient_loader_variables'] = sorted(old_environment)
            try:
                for key in list(os.environ):
                    if key.startswith('LD_'):
                        del os.environ[key]
                os.environ.update(runtime_environment)
                sys.argv = [str(runtime / 'recipe/check.py'), '--prefix', str(payload), '--output', str(output)]
                record['functional_argv'] = sys.argv[:]
                save(record_file, record)
                try:
                    runpy.run_path(sys.argv[0], run_name='__main__')
                    code = 0
                except SystemExit as error:
                    code = error.code
                record['functional_returncode'] = code
                require(code == 0, 'Prusti five-case functional profile failed')
            finally:
                sys.argv = original_argv
                for key in list(os.environ):
                    if key.startswith('LD_'):
                        del os.environ[key]
                os.environ.update(old_environment)
        record['expanded_runtime_removed'] = True
        record['status'] = 'passed'
        save(record_file, record)
        print(json.dumps({'passed': True, 'capsule_evidence': str(record_file)}))
        return 0
    except BaseException as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        save(record_file, record)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
