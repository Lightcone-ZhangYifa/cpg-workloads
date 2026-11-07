"""Actual, bounded functional checks; all tools run from pinned offline inputs."""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import resource
import shutil
import subprocess
import tempfile
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check(prefix, work):
    prefix, evidence_root = Path(prefix).resolve(), Path(work).resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='run-', dir=evidence_root))
    spec = importlib.util.spec_from_file_location('cpg_runtime', prefix / 'cpg_resource_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = None
    log = []

    def run(tool, arguments, *, cwd=work, ok=True, timeout=180):
        cmd = module.command(runtime, tool, [str(arg) for arg in arguments])
        before = time.monotonic()
        limit = None
        if tool in ('coqc', 'coqchk'):
            limit = lambda: resource.setrlimit(resource.RLIMIT_AS, (640 * 1024**2, 640 * 1024**2))
        process = subprocess.run(cmd, cwd=cwd, env=runtime['env'], capture_output=True,
                                 text=True, timeout=timeout, preexec_fn=limit)
        row = {'tool': tool, 'argv': cmd, 'returncode': process.returncode,
               'stdout': process.stdout, 'stderr': process.stderr,
               'seconds': time.monotonic() - before}
        log.append(row)
        (work / 'commands.json').write_text(json.dumps(log, indent=2) + '\n')
        if ok and process.returncode != 0:
            raise RuntimeError(json.dumps(row))
        return process

    profile = json.loads((prefix / 'input-lock.json').read_text())['profile']
    result = {'profile': profile, 'status': 'running', 'run_relative_path': work.name,
              'evidence_schema_version': 1}
    try:
        runtime = module.prepare(prefix, work / 'runtime')
        result['native_runtime_compatibility'] = json.loads(runtime['native_runtime_compatibility'].read_text())
        require(result['native_runtime_compatibility']['status'] == 'passed', 'Original runtime ABI gate failed')
        run('rustc', ['-Vv'])
        if profile == 'rustsmith':
            # Fixed seed and single-threaded selection avoid global RNG races.
            for directory in ('first', 'repeat'):
                run('rustsmith', ['-s', '1', '-n', '1', '-t', '1', '--directory',
                                 work / directory, 'BASE_SELECTION'])
            first, repeat = work / 'first/file0', work / 'repeat/file0'
            source = first / 'file0.rs'
            require(source.read_bytes() == (repeat / 'file0.rs').read_bytes(), 'Seed is not reproducible')
            require((first / 'file0.txt').read_bytes() == (repeat / 'file0.txt').read_bytes(),
                    'Generated program arguments are not reproducible')
            # This fixed seed requires no program arguments.
            require((first / 'file0.txt').read_text().strip() == '', 'Unexpected arguments for the pinned seed')
            outputs = []
            for optimization in ('0', '3'):
                exe = work / ('rustsmith-O' + optimization)
                run('rustc', [source, '-C', 'opt-level=' + optimization,
                              '-C', 'overflow-checks=on', '-o', exe])
                p = subprocess.run([str(exe)], cwd=work, env=runtime['env'],
                                   text=True, capture_output=True, timeout=30)
                log.append({'tool': 'generated-program', 'optimization': optimization,
                            'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
                require(p.returncode == 0, 'Generated RustSmith program failed: ' + p.stderr)
                outputs.append(p.stdout)
            require(outputs[0] == outputs[1], 'Optimization levels disagree')
            require(outputs[0] == 'Program Seed: 1\n18270019056701947067\n', 'Pinned output witness changed')
            result.update(seed=1, selection='BASE_SELECTION', optimization_levels=[0, 3],
                          overflow_checks=True, source_sha256=module.sha256(source),
                          output=outputs[0], repeated_generation_identical=True)
        elif profile == 'aeneas':
            source = work / 'borrow.rs'
            shutil.copy2(prefix / 'examples/borrow.rs', source)
            run('charon', ['rustc', '--preset', 'aeneas', '--sysroot', 'default',
                           '--dest-file', work / 'borrow.llbc', '--', '--crate-type=lib', source])
            coq = work / 'coq'
            coq.mkdir()
            run('aeneas', ['-backend', 'coq', '-no-progress-bar', '-dest', coq,
                           work / 'borrow.llbc'])
            for file in ('BorrowProof.v', 'BorrowBad.v'):
                shutil.copy2(prefix / 'examples' / file, coq / file)
            for file in ('Primitives.v', 'Borrow.v', 'BorrowProof.v'):
                p = run('coqc', ['-q', '-R', '.', 'Lib', file], cwd=coq)
            require('Closed under the global context' in p.stdout, 'The theorem has unexpected assumptions')
            bad = run('coqc', ['-q', '-R', '.', 'Lib', 'BorrowBad.v'], cwd=coq, ok=False)
            require(bad.returncode != 0 and 'Unable to unify' in bad.stderr,
                    'Wrong postcondition did not fail with the expected proof diagnostic')
            result.update(backend='Coq 8.18.0', positive_proof='passed',
                          theorem='replace_selected_spec', theorem_assumptions='none',
                          wrong_postcondition='rejected',
                          extracted_ir_sha256=module.sha256(work / 'borrow.llbc'),
                          generated_coq_sha256=module.sha256(coq / 'Borrow.v'),
                          configuration='upstream -R . Lib; unmodified generated definitions')
        elif profile == 'rustlantis':
            shutil.copy2(prefix / 'examples/config.toml', work / 'config.toml')
            runtime['env'].update(RUST_LOG='debug', RUSTLANTIS_CONFIG=str(work / 'config.toml'),
                                  RAYON_NUM_THREADS='1')
            rows = []
            for seed in (104, 105, 106):
                generated = run('generate', [str(seed)])
                source = work / ('seed-' + str(seed) + '.rs')
                source.write_text(generated.stdout)
                if seed == 104:
                    repeated = run('generate', [str(seed)])
                    require(repeated.stdout == generated.stdout, 'MIR generation is not reproducible')
                run('difftest', [source])
                outputs = []
                for backend, flags in (('llvm', ['-Cllvm-args=-protect-from-escaped-allocas=true']),
                                       ('cranelift', ['-Zcodegen-backend=cranelift'])):
                    exe = work / (str(seed) + '-' + backend)
                    run('rustc', [source, '-Zmir-opt-level=0', '-Copt-level=0', *flags, '-o', exe])
                    p = subprocess.run([str(exe)], cwd=work, env=runtime['env'],
                                       text=True, capture_output=True, timeout=30)
                    log.append({'tool': 'generated-program', 'seed': seed, 'backend': backend,
                                'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
                    require(p.returncode == 0, 'Generated MIR program failed: ' + p.stderr)
                    outputs.append(p.stdout)
                require(outputs[0] == outputs[1], 'LLVM and Cranelift disagree')
                rows.append({'seed': seed, 'source_sha256': module.sha256(source),
                             'llvm_stdout': outputs[0], 'cranelift_stdout': outputs[1]})
            result.update(seeds=rows, backends=['LLVM', 'Cranelift'],
                          upstream_difftest='passed', repeated_generation_identical=True)
        else:
            raise ValueError('Unknown functional profile')
        result['status'] = 'passed'
    except BaseException as error:
        result.update(status='failed', error=str(error))
        raise
    finally:
        result['commands'] = log
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (evidence_root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
        # Runtime is reproducible from the immutable inputs; evidence stays small.
        shutil.rmtree(work / 'runtime', ignore_errors=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    check(args.prefix, args.work)
