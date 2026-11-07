"""Verify and expand the frozen runtime, then execute the actual Rust profile."""
from pathlib import Path
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import uuid

from compiler_playground.packages.archive import verify_package
from compiler_playground.packages.compatibility import check_binary_runtime
from compiler_playground.packages.manager import current_target
from runtime_environment import build_environment


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    require(len(sys.argv) == 2, 'Usage: check.py INSTALLED_PREFIX')
    prefix, build = Path(sys.argv[1]).resolve(), Path.cwd()
    require(not build.resolve().is_relative_to(prefix), 'Writable build must be outside the installed prefix')
    evidence = build / 'functional-evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    runtime_build = build / 'runtime-build'
    runtime_build.mkdir(exist_ok=True)
    frozen_lock = Path(__file__).with_name('capsule-lock.json').read_bytes()
    require((prefix / 'capsule-lock.json').read_bytes() == frozen_lock,
            'Installed capsule identity differs from the frozen recipe helper')
    lock = json.loads(frozen_lock)
    record = {'resource_id': lock['id'], 'capsule_sha256': lock['sha256'],
              'capsule_bytes': lock['bytes'],
              'verification': 'Original CPG verify_package, then original expanded ELF gate'}
    record_path = evidence / ('capsule-' + uuid.uuid4().hex + '.json')

    def save():
        record_path.write_text(json.dumps(record, indent=2) + '\n')

    save()
    try:
        with tempfile.TemporaryDirectory(prefix='creusot-runtime-', dir=runtime_build) as temporary, \
                tempfile.TemporaryDirectory(prefix='cpg-creusot-', dir='/tmp') as process_temp:
            tree = Path(temporary) / 'tree'
            verified = verify_package(prefix / 'runtime.cpgpkg.tar.gz', extract=tree,
                                      expected_sha256=lock['sha256'], expected_bytes=lock['bytes'])
            require(verified['manifest']['package']['id'] == lock['id'], 'Wrong runtime identity')
            raw_manifest = (prefix / 'runtime-manifest.json').read_bytes()
            require(hashlib.sha256(raw_manifest).hexdigest() == lock['manifest_file_sha256'],
                    'Runtime manifest file changed')
            require(json.loads(raw_manifest) == verified['manifest'], 'Runtime member manifest differs')
            record.update(verified=True, manifest_sha256=lock['manifest_file_sha256'])
            payload = tree / 'payload'
            config = json.loads((payload / 'profile-config.json').read_text())
            require(config['private_library_dirs'] == lock['private_library_dirs'],
                    'Capsule ELF gate and actual runtime library configuration differ')
            run_dir = evidence / ('run-' + uuid.uuid4().hex)
            run_dir.mkdir()
            environment, declared = build_environment(payload, config, run_dir, Path(process_temp))
            target, rows = current_target(), []
            record['compatibility'] = {'actual_target': target, 'declared_environment': declared,
                                       'status': 'checking', 'evidence': rows}
            save()
            try:
                check_binary_runtime(payload, actual_target=target, environment=environment, evidence=rows)
                require(any(row.get('kind') == 'elf_runtime' for row in rows), 'No real runtime ELF checked')
            except BaseException as error:
                record['compatibility'].update(status='failed', error=repr(error))
                save()
                raise
            record['compatibility']['status'] = 'passed'
            argv = [sys.executable, str(Path(__file__).with_name('functional.py')), str(payload), str(run_dir)]
            record['functional_argv'] = argv
            record['private_process_temp'] = process_temp
            stdout_file = record_path.with_suffix('.stdout.log')
            stderr_file = record_path.with_suffix('.stderr.log')
            record.update(stdout=stdout_file.name, stderr=stderr_file.name)
            save()
            process = None
            try:
                with stdout_file.open('w') as out, stderr_file.open('w') as err:
                    process = subprocess.Popen(argv, cwd=build, env=environment, stdout=out, stderr=err,
                                               start_new_session=True)
                    record['process_group'] = process.pid
                    save()
                    process.wait(timeout=1100)
                record.update(functional_returncode=process.returncode, timed_out=False)
            except subprocess.TimeoutExpired:
                record.update(functional_returncode=None, timed_out=True)
                raise
            finally:
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    if process.poll() is None:
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                    # Also remove any background solver descendants after their parent exits.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for field, path in (('stdout', stdout_file), ('stderr', stderr_file)):
                    if path.exists():
                        record[field + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                record['owned_process_group_cleaned'] = process is not None
                save()
            save()
            print(stdout_file.read_text(), end='')
            print(stderr_file.read_text(), end='', file=sys.stderr)
            require(process.returncode == 0, 'Actual Rust and Why3 functional profile failed')
            functional_result_path = run_dir / 'result.json'
            functional_result_bytes = functional_result_path.read_bytes()
            functional_result = json.loads(functional_result_bytes)
            require(functional_result.get('status') == 'passed'
                    and functional_result.get('run_relative_path') == run_dir.name,
                    'The actual functional result is absent, incomplete, or from another run')
            cases = functional_result.get('cases', [])
            require(len(cases) == 3 and {(item['fixture'], item['case']) for item in cases} == {
                ('sum', 'good'), ('unused_in_loop', 'good'), ('unused_in_loop', 'bad_postcondition')},
                'Actual functional receipt does not cover all three fixed cases')
            for item in cases:
                if item['case'] == 'good':
                    require(item.get('status') == 'proved'
                            and all(goal['polarity'] == 'original' and goal['answer'] == 'Valid'
                                    for goal in item['original_goal_results']),
                            'A positive result contains an unproved or negated goal')
                else:
                    counterproof, witness = item.get('negative_counterproof', {}), item.get('native_witness', {})
                    require(item.get('status') == 'false_post_refuted_and_native_witness_confirmed'
                            and item.get('ordinary_unknown_is_not_a_pass') is True
                            and counterproof.get('status') == 'passed'
                            and counterproof.get('polarity') == 'negated_original_goal'
                            and counterproof.get('original_bad_goal_proved') is False
                            and witness.get('status') == 'passed'
                            and witness.get('actual') == 10 and witness.get('bad_postcondition_holds') is False
                            and witness.get('verified_source_sha256') == item['rust_sha256'],
                            'A negative result lacks its independent proof and actual same-source witness')
            record['functional_result'] = str(functional_result_path.relative_to(evidence))
            record['functional_result_sha256'] = hashlib.sha256(functional_result_bytes).hexdigest()
            save()
        record['expanded_runtime_removed'] = True
        record['private_process_temp_removed'] = True
        record['status'] = 'passed'
        save()
    except BaseException as error:
        record.update(status='failed', error=repr(error))
        save()
        raise


if __name__ == '__main__':
    main()
