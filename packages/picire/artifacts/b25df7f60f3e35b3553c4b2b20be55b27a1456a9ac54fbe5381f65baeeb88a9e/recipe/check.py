#!/usr/bin/env python3
"""Verify exact private dependencies and actual Picire reductions and upstream tests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import traceback
import xml.etree.ElementTree as ET
import zipfile

VERSION = '21.8'


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--expected-version', default=VERSION)
    parser.add_argument('--case', choices=['version', 'reduction'], default='reduction')
    args = parser.parse_args()
    args.build.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='picire-' + args.case + '-', dir=args.build))
    summary = {'schema_version': 1, 'resource_id': 'picire', 'version': VERSION, 'case': args.case,
               'status': 'failed', 'evidence': str(work), 'scope': 'Native CPython 3.12; original API/CLI matrix and explicit known-answer controls'}
    steps = []
    prefix = args.prefix.resolve(strict=True)
    share, runtime = prefix / 'share/picire', prefix / 'runtime'
    python = runtime / 'bin/python'
    environment = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONOPTIMIZE', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'):
        environment.pop(name, None)
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PIP_NO_INDEX='1',
                       PIP_CONFIG_FILE=os.devnull, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                       PATH=str(runtime / 'bin') + ':/usr/bin:/bin')

    def run(argv, name, expected=0, cwd=None, timeout=480):
        completed = subprocess.run([str(x) for x in argv], cwd=cwd or work, env=environment,
                                   stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        (work / (name + '.stdout')).write_bytes(completed.stdout)
        (work / (name + '.stderr')).write_bytes(completed.stderr)
        steps.append({'name': name, 'argv': [str(x) for x in argv], 'returncode': completed.returncode})
        save(work / 'commands.json', steps)
        need(completed.returncode == expected, name + ' returned ' + str(completed.returncode))
        return completed

    try:
        need(args.expected_version == VERSION, 'Unexpected requested Picire version')
        profile = json.loads((share / 'profile.json').read_text())
        closure = json.loads((share / 'closure.json').read_text())
        need(profile['resource_id'] == 'picire' and profile['version'] == VERSION, 'Incorrect installed Picire identity')
        need(digest(python) == profile['interpreter_binary_sha256'], 'Private interpreter changed')
        need(digest(profile['interpreter']['base_executable']) == profile['base_interpreter_sha256'],
             'The declared base interpreter changed; rebuild this source profile')
        original = [{'path': p.relative_to(share / 'source').as_posix(), 'sha256': digest(p),
                     'bytes': p.stat().st_size, 'mode': p.stat().st_mode & 0o777}
                    for p in sorted((share / 'source').rglob('*')) if p.is_file() and not p.is_symlink()]
        need(original == profile['original_source_files'], 'Original upstream source/tests changed')
        code = '''import hashlib,importlib.metadata as m,json,pathlib,sys,picire
p=pathlib.Path(sys.prefix).resolve()
rows={}
for d in m.distributions():
 f=pathlib.Path(d._path)/'METADATA'
 if not f.resolve().is_relative_to(p):raise ValueError('ambient distribution detected')
 rows[d.metadata['Name']]={'version':d.version,'metadata_sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
if not pathlib.Path(picire.__file__).resolve().is_relative_to(p):raise ValueError('ambient picire detected')
print(json.dumps({'distributions':rows,'module':picire.__file__,'version':picire.__version__,'python_version':list(sys.version_info[:3]),'assertions_enabled':__debug__},sort_keys=True))'''
        installed = json.loads(run([python, '-I', '-c', code], 'selected-interpreter-identity', timeout=30).stdout)
        need(installed['python_version'][:2] == [3, 12] and installed['version'] == VERSION
             and installed['assertions_enabled'], 'Selected interpreter/version/assertion contract differs')
        actual = {normalized(k): v for k, v in installed['distributions'].items()}
        expected = {normalized(k): v for k, v in profile['distributions'].items()}
        need({k: v['version'] for k, v in actual.items()} == expected, 'Installed distribution closure differs')
        binding = []
        for row in closure['distributions']:
            declaration = row['source']
            wheel = share / 'wheels' / Path(declaration['material_path']).name
            need(wheel.stat().st_size == declaration['bytes'] and digest(wheel) == declaration['sha256'], 'Private input wheel changed')
            with zipfile.ZipFile(wheel) as archive:
                metas = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
                need(len(metas) == 1, 'Wheel metadata is ambiguous')
                sha = hashlib.sha256(archive.read(metas[0])).hexdigest()
                need(actual[normalized(row['distribution'])]['metadata_sha256'] == sha, 'Installed metadata differs from locked wheel')
                binding.append({'distribution': row['distribution'], 'version': row['version'],
                                'wheel_sha256': declaration['sha256'], 'metadata_sha256': sha})
        built = share / profile['built_wheel']['file']
        need(digest(built) == profile['built_wheel']['sha256'], 'Built target wheel changed')
        with zipfile.ZipFile(built) as archive:
            meta = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
            need(hashlib.sha256(archive.read(meta)).hexdigest() == actual['picire']['metadata_sha256'], 'Target metadata differs from built wheel')
        module_dir = Path(installed['module']).parent
        for patch in profile['compatibility_patch']['files']:
            need(digest(module_dir / Path(patch['path']).name) == patch['result_sha256'], 'Installed compatibility patch differs')
        save(work / 'wheel-metadata-bindings.json', binding)
        version = run([prefix / 'bin/picire', '--version'], 'launcher-version', timeout=30)
        need(re.search(rb'(?<![0-9.])21\.8(?![0-9.])', version.stdout + version.stderr), 'CLI version differs')
        summary.update(private_distributions=len(actual), original_source_files=len(original), wheel_metadata_bindings=len(binding))
        if args.case == 'reduction':
            api = work / 'api-control.py'
            api.write_text('''import json,picire
from picire.shared_cache import SharedCacheManager
class Interesting:
 def __call__(self,config,config_id):
  return picire.Outcome.FAIL if 3 in config and 11 in config else picire.Outcome.PASS
answer=[]
try:
 for cls in [picire.DD,picire.ParallelDD,picire.CombinedParallelDD]:
  kw={} if cls is picire.DD else {'proc_num':2}
  result=cls(Interesting(),**kw)(list(range(20)))
  if result != [3,11]:raise ValueError('wrong known-answer reduction')
  for i in range(len(result)):
   if Interesting()(result[:i]+result[i+1:],()) is not picire.Outcome.PASS:raise ValueError('result is not one-minimal')
  answer.append({'algorithm':cls.__name__,'result':result,'one_minimal':True})
 try:picire.DD(Interesting())([1,2])
 except AssertionError:negative=True
 else:raise ValueError('initial passing configuration was accepted')
 print(json.dumps({'status':'passed','algorithms':answer,'initial_passing_input_rejected':negative}))
finally:
 for manager in SharedCacheManager._managers.values():manager.shutdown()
''')
            control = json.loads(run([python, '-I', api], 'api-known-answer', timeout=90).stdout)
            need(control['status'] == 'passed' and len(control['algorithms']) == 3, 'Missing API controls')
            summary['api_controls'] = control
            run([prefix / 'bin/picire', '--input=' + str(work / 'missing.c'), '--test=/bin/true'],
                'missing-input', expected=2, timeout=30)
            run([prefix / 'bin/picire', '--input=' + str(work / 'missing.c'), '--test=/bin/true', '--granularity=1'],
                'invalid-granularity', expected=2, timeout=30)
            tests = work / 'upstream-tests'
            shutil.copytree(share / 'source/tests', tests)
            collection = run([python, '-I', '-m', 'pytest', '--import-mode=importlib', '--collect-only', '-q', str(tests)],
                             'upstream-collection', cwd=tests, timeout=60)
            expected_cases = sorted(line.strip() for line in collection.stdout.decode().splitlines()
                                    if line.startswith(('test_api.py::', 'test_cli.py::')))
            need(len(expected_cases) == 176 and len(set(expected_cases)) == 176,
                 'Exact pinned upstream test inventory differs: ' + str(len(expected_cases)))
            report = work / 'upstream-junit.xml'
            run([python, '-I', '-m', 'pytest', '--import-mode=importlib', '-q', '--junitxml=' + str(report), str(tests)],
                'upstream-results', cwd=tests, timeout=420)
            tree = ET.parse(report)
            cases = tree.findall('.//testcase')
            observed = []
            for case in cases:
                need(not list(case.findall('failure')) and not list(case.findall('error')) and not list(case.findall('skipped')),
                     'An upstream test failed, errored or skipped')
                parts = case.attrib['classname'].split('.')
                observed.append(parts[-2] + '.py::' + parts[-1] + '::' + case.attrib['name'])
            need(sorted(observed) == expected_cases, 'Executed upstream test list differs from the collected original matrix')
            save(work / 'upstream-executed-cases.json', observed)
            summary['upstream'] = {'collected': len(expected_cases), 'executed': len(cases),
                                   'passed': len(cases), 'failed': 0, 'errors': 0, 'skipped': 0,
                                   'original_test_files_unchanged': True}
            summary['negative_controls'] = ['wrong-version', 'initial-passing-input', 'missing-input', 'invalid-granularity']
        summary['status'] = 'passed'
        save(work / 'summary.json', summary)
        print(json.dumps(summary, sort_keys=True))
    except BaseException as error:
        summary['error'] = type(error).__name__ + ': ' + str(error)
        save(work / 'summary.json', summary)
        raise


if __name__ == '__main__':
    main()
