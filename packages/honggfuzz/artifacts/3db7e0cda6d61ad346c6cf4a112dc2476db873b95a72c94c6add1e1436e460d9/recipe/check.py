#!/usr/bin/env python3
"""Run bounded real local fuzzing, crash discovery, and dependency-origin checks."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    args.build.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='honggfuzz-functional-', dir=args.build))
    share = prefix / 'share/honggfuzz'
    profile = json.loads((prefix / 'share/compiler-playground/honggfuzz/profile.json').read_text())
    env = dict(os.environ, PATH='/usr/bin:/bin', LC_ALL='C.UTF-8', PYTHONDONTWRITEBYTECODE='1',
               HFUZZ_CC_PATH='/usr/bin/gcc', HFUZZ_CXX_PATH='/usr/bin/g++', CPG_HONGGFUZZ_MARKER=str(output / 'callback-marker'))
    for variable in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'CPG_HFUZZ_INCLUDE',
                     'HFUZZ_LHFUZZ_PATH', 'HFUZZ_LHFCOMMON_PATH', 'HFUZZ_LHFNETDRIVER_PATH'):
        env.pop(variable, None)
    commands = []

    def run(label, argv, *, expected=0, timeout=40):
        argv = list(map(str, argv))
        process = subprocess.Popen(argv, cwd=output, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            (output / (label + '.stdout')).write_bytes(stdout)
            (output / (label + '.stderr')).write_bytes(stderr)
            raise RuntimeError('Bounded functional command timed out: ' + label)
        (output / (label + '.stdout')).write_bytes(stdout)
        (output / (label + '.stderr')).write_bytes(stderr)
        commands.append({'label': label, 'argv': argv, 'returncode': process.returncode, 'expected_returncode': expected,
                         'stdout': label + '.stdout', 'stderr': label + '.stderr'})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2, sort_keys=True) + '\n')
        need(process.returncode != 0 if expected == 'nonzero' else process.returncode == expected, 'Unexpected command result: ' + label)
        return stdout.decode(errors='replace'), stderr.decode(errors='replace')

    runtime = share / 'runtime'
    private = profile['private_runtime']
    library_origins = {}
    for binary in ('honggfuzz', 'hfuzz-cc'):
        listing, _ = run(binary + '-library-origins', [runtime / private['loader'], '--library-path', runtime / private['library_directory'], '--list', prefix / 'libexec' / binary])
        observed = []
        for name in re.findall(r'=> (/\S+)\s+\(', listing):
            path = Path(name).resolve()
            need(path.is_relative_to(runtime), 'A binary loaded a host library in place of a fixed private dependency')
            observed.append({'path': path.relative_to(runtime).as_posix(), 'sha256': sha(path)})
        need(observed == private['resolved_libraries'][binary], 'Runtime dependency identity changed after relocation')
        library_origins[binary] = observed
    run('help', [prefix / 'bin/honggfuzz', '--help'])
    run('invalid-option', [prefix / 'bin/honggfuzz', '--cpg-invalid-option'], expected='nonzero')
    run('missing-input-directory', [prefix / 'bin/honggfuzz', '-v', '-n', '1', '-i', output / 'absent-inputs', '--', '/usr/bin/true', '___FILE___'], expected='nonzero')
    api = output / 'persistent-api'
    run('compile-installed-api-target', [prefix / 'bin/hfuzz-gcc', '-O1', '-g', share / 'api_target.c', '-o', api])
    symbol_text, _ = run('instrumentation-symbols', ['/usr/bin/nm', api])
    need('__sanitizer_cov_trace_pc' in symbol_text and 'LLVMFuzzerTestOneInput' in symbol_text, 'The target lacks actual installed software instrumentation/API')
    for name, content in (('good-corpus', b'GOOD'), ('crash-corpus', b'CRSH')):
        (output / name).mkdir()
        (output / name / 'seed').write_bytes(content)
    sessions = []

    def fuzz(label, corpus, target, *, persistent, crash=False):
        work = output / (label + '-work')
        argv = [prefix / 'bin/honggfuzz', '-v', '-n', '1', '-N', '16', '-r', '0', '--run_time', '8',
                '-i', corpus, '-W', work, '-o', output / (label + '-coverage'), '--rlimit_core', '0']
        if persistent:
            argv += ['-P', '-z']
        else:
            argv += ['-x']
        if crash:
            argv += ['--exit_upon_crash', '--exit_code_upon_crash', '77']
        argv += ['--', target]
        if not persistent:
            argv += ['___FILE___']
        stdout, stderr = run(label, argv, expected=77 if crash else 0)
        combined = stdout + '\n' + stderr
        summaries = re.findall(r'Summary iterations:(\d+).*?crashes_count:(\d+) timeout_count:(\d+)', combined)
        need(len(summaries) == 1, 'Actual fuzzer summary is missing: ' + label)
        iterations, crashes, timeouts = map(int, summaries[0])
        need(iterations > 0 and timeouts == 0, 'The fuzzer did not execute bounded successful target iterations')
        files = [p for p in work.iterdir() if p.is_file() and p.name.startswith('SIG')]
        if crash:
            need(crashes > 0 and files, 'The known crash was not actually discovered and saved')
        else:
            need(crashes == 0 and not files, 'The valid persistent target unexpectedly crashed')
        sessions.append({'label': label, 'iterations': iterations, 'crashes': crashes, 'timeouts': timeouts,
                         'persistent': persistent, 'software_instrumentation': persistent,
                         'saved_crashes': [{'path': str(p.relative_to(output)), 'sha256': sha(p), 'bytes': p.stat().st_size} for p in files]})

    fuzz('persistent-valid', output / 'good-corpus', api, persistent=True)
    marker = output / 'callback-marker'
    need(marker.is_file() and marker.read_bytes() and set(marker.read_bytes()) == {ord('G')}, 'Known input did not reach the real persistent API callback')
    callback_count = marker.stat().st_size
    fuzz('persistent-crash', output / 'crash-corpus', api, persistent=True, crash=True)
    upstream = share / 'upstream-examples/badcode1.c'
    need(sha(upstream) == profile['upstream_tests']['upstream_example_sha256'], 'Original upstream demo source changed')
    badcode = output / 'upstream-badcode1'
    run('compile-original-upstream-example', ['/usr/bin/gcc', '-O0', '-g', '-fno-stack-protector', '-U_FORTIFY_SOURCE', '-D_FORTIFY_SOURCE=0', upstream, '-o', badcode])
    bad_corpus = output / 'upstream-badcode-corpus'
    bad_corpus.mkdir();(bad_corpus / 'long-line').write_bytes(b'A' * 127 + b'\n')
    fuzz('original-upstream-badcode1', bad_corpus, badcode, persistent=False, crash=True)
    result = {'status': 'passed', 'prefix': str(prefix), 'execution_directory': str(output),
        'commands_executed': len(commands), 'negative_cli_commands': 2, 'fuzz_sessions': sessions,
        'persistent_callback_observed_count': callback_count, 'upstream_demo_executions': 1,
        'upstream_demo_source_sha256': sha(upstream), 'private_runtime_libraries': library_origins,
        'actual_host_compiler_sha256': sha(Path('/usr/bin/gcc').resolve()),
        'hardware_perf_pmu': 'not_run', 'upstream_automated_test_suite': 'not_present_in_locked_snapshot',
        'scope': 'Locally created instrumented API target and original upstream badcode1 example, own-child ptrace; no external process targets'}
    (output / 'checks.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
