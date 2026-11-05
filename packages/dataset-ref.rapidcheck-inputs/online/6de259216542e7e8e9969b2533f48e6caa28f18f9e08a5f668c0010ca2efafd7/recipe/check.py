#!/usr/bin/env python3
"""Run installed property checks, a false property, and the original upstream test binary."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve(strict=True)
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    profile = json.loads((prefix / 'share/compiler-playground' / config['id'] / 'profile.json').read_text())
    if profile['main_commit'] != config['main_commit']:
        raise ValueError('Installed RapidCheck source identity differs')
    environment = dict(os.environ, LC_ALL='C', RC_PARAMS=config['rc_params'])
    for key in list(environment):
        if key.startswith(('LD_', 'GTEST_', 'GMOCK_')):
            environment.pop(key)
    report = {'resource_id': config['id'], 'status': 'running', 'commands': [],
              'RC_PARAMS': config['rc_params'], 'consumers': []}

    def run(argv, expected=0):
        command = list(map(str, argv))
        with tempfile.TemporaryDirectory(prefix='cpg-rapidcheck-run-') as temporary:
            completed = subprocess.run(command, env=environment, cwd=temporary,
                                       capture_output=True, text=True, timeout=300)
        report['commands'].append({'argv': command, 'returncode': completed.returncode,
                                   'stdout': completed.stdout, 'stderr': completed.stderr})
        if completed.returncode != expected:
            raise RuntimeError('Unexpected native property-check exit status: ' + command[0])
        return completed

    try:
        for kind in ('static', 'shared'):
            executable = prefix / 'bin' / ('cpg-native-check' + ('' if kind == 'static' else '-shared'))
            completed = run([executable])
            value = json.loads(completed.stdout)
            if value != {'status': 'passed', 'properties': 4, 'executed_cases': 400}:
                raise RuntimeError('Property consumer executed a different case count')
            if len(re.findall(r'OK, passed 100 tests', completed.stderr)) != 4:
                raise RuntimeError('Upstream RapidCheck diagnostic does not confirm all four property runs')
            false_property = run([executable, '--cpg-fail'], expected=1)
            if ('deliberate property failure detected' not in false_property.stdout
                    or 'Falsifiable after' not in false_property.stderr):
                raise RuntimeError('The known false property was not falsified')
            links = run(['ldd', executable]).stdout
            matching = [line for line in links.splitlines() if 'librapidcheck.so' in line]
            if 'not found' in links or (kind == 'static' and matching):
                raise RuntimeError('The property consumer has incorrect runtime linkage')
            if kind == 'shared' and (len(matching) != 1 or str(prefix) + '/bin/../lib/' not in matching[0]):
                raise RuntimeError('The shared library resolved another prefix')
            report['consumers'].append({'link': kind, **value, 'false_property_rejected': True})
        upstream = run([prefix / 'libexec' / config['id'] / 'rapidcheck_tests'])
        result = re.search(r'All tests passed \((\d+) assertions? in (\d+) test cases?\)', upstream.stdout)
        if result is None or int(result[1]) != profile['upstream']['inner_assertions_passed'] or int(result[2]) != profile['upstream']['inner_test_cases_passed']:
            raise RuntimeError('Installed upstream RapidCheck test count or assertion total differs')
        report.update(status='passed', upstream_assertions_passed=int(result[1]), upstream_cases_passed=int(result[2]))
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
