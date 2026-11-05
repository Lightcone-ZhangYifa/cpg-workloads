#!/usr/bin/env python3
"""Exercise packaged binaries without needing the source build or compiler."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve(strict=True)
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    profile = json.loads((prefix / 'share/compiler-playground' / config['id'] / 'profile.json').read_text())
    assert profile['resource_id'] == config['id']
    assert profile['upstream_version'] == config['upstream_version']
    environment = dict(os.environ)
    blocked = {'LIBRARY_PATH', 'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'}
    for key in list(environment):
        if key.startswith(('LD_', 'GTEST_', 'GMOCK_')) or key in blocked:
            environment.pop(key)
    report = {'resource_id': config['id'], 'status': 'running', 'prefix': str(prefix), 'commands': []}

    def run(argv, expected=0):
        command = list(map(str, argv))
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=180)
        report['commands'].append({'argv': command, 'returncode': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode != expected:
            raise RuntimeError('Unexpected exit status for ' + command[0])
        return result.stdout

    try:
        with tempfile.TemporaryDirectory(prefix='cpg-native-functional-') as directory:
            temporary = Path(directory)
            report['consumers'] = []
            for kind in ('static', 'shared'):
                executable = prefix / 'bin' / ('cpg-native-check' + ('' if kind == 'static' else '-shared'))
                if config['family'] == 'googletest':
                    junit = temporary / (kind + '.xml')
                    run([executable, '--gtest_output=xml:' + str(junit)])
                    root = ET.parse(junit).getroot()
                    cases = root.findall('.//testcase')
                    if len(cases) != 5 or any(c.find('failure') is not None or c.find('skipped') is not None for c in cases):
                        raise RuntimeError('GoogleTest/GoogleMock consumer did not execute its exact five checks')
                    negative = run([executable, '--cpg-fail'], expected=1)
                    if '[  FAILED  ]' not in negative:
                        raise RuntimeError('Deliberately failing assertion had no expected diagnostic')
                    outcome = {'tests_passed': len(cases), 'deliberate_failure_rejected': True}
                else:
                    outcome = json.loads(run([executable]))
                    if (outcome.get('status') != 'passed' or outcome.get('checks') != 18
                            or outcome.get('invalid_inputs_rejected') != 4):
                        raise RuntimeError('simdjson consumer has incomplete semantic checks')
                    negative = run([executable, '--cpg-fail'], expected=1)
                    if 'deliberate answer mismatch detected' not in negative:
                        raise RuntimeError('Deliberate semantic mismatch lacked its diagnostic')
                links = run(['ldd', executable])
                if 'not found' in links:
                    raise RuntimeError('Dynamic dependency unresolved')
                for name in config['libraries']:
                    matching = [line for line in links.splitlines() if 'lib' + name + '.so' in line]
                    if kind == 'shared' and (len(matching) != 1 or str(prefix) + '/bin/../lib/' not in matching[0]):
                        raise RuntimeError('Shared consumer resolves another installation for ' + name)
                    if kind == 'static' and matching:
                        raise RuntimeError('Static consumer uses a shared resource library')
                report['consumers'].append({'link': kind, 'result': outcome})
            report['upstream_programs'] = []
            if config['family'] == 'simdjson':
                for name in ('padded_string_tests', 'unicode_tests'):
                    run([prefix / 'libexec' / config['id'] / name])
                    report['upstream_programs'].append(name)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
