#!/usr/bin/env python3
"""Run historical SSA compilation and QEMU user-mode ia32 execution, offline.

The check reads only installed inputs and uses an isolated temporary directory.
It does not infer proof validity from compiler execution. Full Coq proof replay
has its own command records and raw log. --output retains this run's evidence.
"""

if not __debug__:
    raise RuntimeError("CPG worker095 integrity checks require unoptimized Python")
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('prefix', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--compiler', type=Path)
    p.add_argument('--runner', type=Path)
    p.add_argument('--runner-libdir', type=Path)
    a = p.parse_args()
    prefix = a.prefix.resolve()
    compiler = (a.compiler or prefix/'bin/ccomp').resolve()
    runner = (a.runner or prefix/'libexec/qemu-i386').resolve()
    fixtures = prefix/'fixtures'
    env = os.environ.copy()
    env['COMPCERT_LIBRARY'] = str(prefix/'runtime')
    env['LC_ALL'] = 'C'
    env['LD_LIBRARY_PATH'] = str((a.runner_libdir or prefix/'lib').resolve())
    records = []
    started = time.monotonic()
    if not compiler.is_file():
        raise FileNotFoundError(compiler)
    if not runner.is_file():
        raise FileNotFoundError(runner)
    for name in ('gcc', 'as', 'ld'):
        if not shutil.which(name):
            raise RuntimeError('Required host command unavailable: '+name)

    def run(argv, cwd, expected=0, reject=False):
        r = subprocess.run([str(x) for x in argv], cwd=cwd, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=120, text=True)
        record = {'argv':[str(x) for x in argv], 'cwd':str(cwd),
                  'returncode':r.returncode, 'output':r.stdout,
                  'expected_returncode':expected,
                  'expected_rejection':reject}
        records.append(record)
        if r.returncode != expected:
            raise AssertionError(json.dumps(record, ensure_ascii=False))
        return r

    with tempfile.TemporaryDirectory(prefix='cpg-worker095-ssa-') as temp:
        work = Path(temp)
        # The historical parser exits before removing its preprocessed input on
        # an error. Keep even that negative-case temporary inside this run.
        env['TMPDIR'] = str(work)
        # Record actual commands/platform versions used by the compiler pipeline.
        for tool in ('gcc','as','ld'):
            run([tool, '--version'], work)
        run([runner, '--version'], work)
        results = []
        for mode, input_name, expected in [
            ('on','ssa-functional.c',0),
            ('off','ssa-functional.c',0),
            ('on','ssa-exit42.c',42),
        ]:
            case = work/(mode+'-'+Path(input_name).stem)
            case.mkdir()
            shutil.copy2(fixtures/input_name, case/input_name)
            shutil.copy2(fixtures/'ia32-start.s', case/'start.s')
            argv = [compiler, '-ssa', mode, '-S']
            if mode == 'on':
                argv += ['-dssa','-ddssa']
            argv += ['-o','program.s',input_name]
            run(argv, case)
            run(['as','--32','start.s','-o','start.o'], case)
            run(['as','--32','program.s','-o','program.o'], case)
            run(['ld','-m','elf_i386','-o','program','start.o','program.o'], case)
            executed = run([runner,case/'program'], case, expected=expected)
            dumps = list(case.glob('*.ssa'))
            if mode == 'on' and not any(x.stat().st_size for x in dumps):
                raise AssertionError('SSA pipeline did not emit a nonempty SSA dump')
            if mode == 'on' and input_name == 'ssa-functional.c':
                # The loop/branch fixture must exercise SSA join assignments.
                text = '\n'.join(x.read_text() for x in dumps)
                if 'ϕ(' not in text and 'phi' not in text.lower():
                    raise AssertionError('Expected SSA phi assignments in loop/join fixture')
            results.append({'ssa_mode':mode,'input':input_name,
                            'input_sha256':sha(case/input_name),
                            'expected_exit':expected,'actual_exit':executed.returncode,
                            'assembly_sha256':sha(case/'program.s'),
                            'executable_sha256':sha(case/'program'),
                            'ssa_dumps':[{'path':x.name,'bytes':x.stat().st_size,'sha256':sha(x)} for x in dumps]})
        bad = work/'negative';bad.mkdir()
        shutil.copy2(fixtures/'ssa-invalid.c',bad/'ssa-invalid.c')
        rejected = run([compiler,'-ssa','on','-S','-o','invalid.s','ssa-invalid.c'],bad,expected=2,reject=True)
        if 'error' not in rejected.stdout.lower():
            raise AssertionError('Expected a compiler error diagnostic for malformed C')
        if (bad/'invalid.s').exists():
            raise AssertionError('Malformed source left an apparently successful assembly output')
        native_compiler = compiler if a.compiler is not None else prefix/'libexec/ccomp.native'
        if not native_compiler.is_file():
            native_compiler = compiler
        result = {'status':'passed','kind':'functional','resource_id':'compcert-ssa',
                  'compiler_sha256':sha(native_compiler),
                  'compiler_entry_sha256':sha(compiler),'compiler_entry':str(compiler),
                  'compiler_selection':'explicit_override' if a.compiler is not None else 'package_default',
                  'cases':results,
                  'executor':{'kind':'qemu-user','target':'i386-linux','path':str(runner),
                              'sha256':sha(runner),'host_compiler_architecture':'x86_64',
                              'hardware_qualification':False},
                  'invalid_source_returncode':rejected.returncode,
                  'proof_scope':'Compiler execution check only; see independent Coq proof replay evidence.',
                  'elapsed_seconds':time.monotonic()-started,'commands':records}
        if a.output:
            out=a.output.resolve()
            if out.exists():raise FileExistsError(out)
            shutil.copytree(work,out)
            (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
