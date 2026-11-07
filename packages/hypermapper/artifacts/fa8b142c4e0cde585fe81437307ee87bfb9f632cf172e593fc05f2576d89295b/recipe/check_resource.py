#!/usr/bin/env python3
"""Run a fresh measured tuning experiment from an installed CPG resource."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from profile_inputs import Profile


BOOTSTRAP = r'''import sys,runpy,pathlib
prefix=pathlib.Path(sys.argv[1]); script=pathlib.Path(sys.argv[2]); args=sys.argv[3:]
sites=list((prefix/'lib').glob('python*/site-packages'))
if len(sites)!=1: raise RuntimeError('One private Python site-packages directory is required')
sys.path[:0]=[str(script.parent),str(sites[0])]
sys.prefix=sys.exec_prefix=str(prefix)
sys.argv=[str(script),*args]
runpy.run_path(str(script),run_name='__main__')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('resource', 'prefix', 'assets', 'build'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    recipe = Path(__file__).resolve().parent
    profile = Profile(args.assets, recipe)
    definition = profile.definition
    if definition['id'] != args.resource:
        raise ValueError('Resource identity differs')
    prefix = Path(args.prefix)
    evidence = Path(args.build) / ('functional-' + uuid.uuid4().hex[:12])
    evidence.mkdir()
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', OPENBLAS_NUM_THREADS='1',
               OMP_NUM_THREADS='1', PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    env.pop('PYTHONPATH', None)
    commands = []

    def execute(argv, name):
        argv = [str(x) for x in argv]
        commands.append(argv)
        with (evidence / (name + '.stdout')).open('w') as stdout, (evidence / (name + '.stderr')).open('w') as stderr:
            result = subprocess.run(argv, env=env, cwd=evidence, stdout=stdout, stderr=stderr)
        if result.returncode:
            raise RuntimeError('Fresh functional command failed; inspect ' + str(evidence / (name + '.stderr')))

    if definition.get('mode') == 'R':
        python = sys.executable
        execute([python, '-S', recipe / 'src/benchmark.py', '--prepare', evidence], 'prepare')
        out = evidence / 'irace'
        out.mkdir()
        env['CPG083_IRACE_OUTPUT'] = str(out)
        execute([python, '-S', recipe / 'src/r_driver.py', '--r-root', prefix / 'R-root',
                 '--r-lib', prefix / 'R-library', '--', '--vanilla', '-f', recipe / 'src/run_irace.R',
                 '--args', out, python, recipe / 'src/irace_target.py'], 'irace')
        execute([python, '-S', recipe / 'src/check_irace.py', '--out', out], 'irace-replay')
    else:
        python = prefix / 'bin/python'
        private = list((prefix / 'lib').glob('python*/site-packages'))
        if len(private) != 1:
            raise RuntimeError('Private Python installation is absent')
        env['PYTHONPATH'] = str(private[0])
        env['PATH'] = str(prefix / 'bin') + os.pathsep + env.get('PATH', '')
        execute([python, '-S', '-c', BOOTSTRAP, prefix, recipe / 'src/benchmark.py', '--prepare', evidence], 'prepare')
        phases = definition.get('cli_phases') or [definition['cli']]
        for index, phase in enumerate(phases):
            parts = [v.replace('{evidence}', str(evidence)).replace('{python}', str(python)) for v in phase]
            execute([python, '-S', '-c', BOOTSTRAP, prefix, recipe / 'src' / parts[0], *parts[1:]], f'phase-{index + 1:02d}')
    result_path = evidence / definition.get('result_subdirectory', args.resource) / 'result.json'
    result = json.loads(result_path.read_text())
    if result.get('status') not in {'passed', 'pass'}:
        raise RuntimeError('The fresh functional result did not pass')
    summary = {'status': 'passed', 'resource': args.resource, 'evidence': str(evidence),
               'result': str(result_path), 'commands': commands, 'prefix': str(prefix),
               'qualification_scope': 'Real local tuning and correctness demonstration; no official benchmark or physical GPU qualification'}
    (evidence / 'check-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))
    print('CPG_WORKER083_CHECK_PASSED')


if __name__ == '__main__':
    main()
