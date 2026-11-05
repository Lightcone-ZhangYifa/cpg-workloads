#!/usr/bin/env python3
"""Run installed upstream executables and fresh consumers at the actual prefix."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--build', type=Path)
    parser.add_argument('--case', choices=('upstream', 'api'), required=True)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    prefix = args.prefix.resolve(strict=True)
    resource = config['id']
    environment = dict(os.environ, LC_ALL='C')
    for name in tuple(environment):
        if name.startswith(('GTEST_', 'GMOCK_')) or name in ('LD_LIBRARY_PATH','LD_PRELOAD','LIBRARY_PATH','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','XML_CATALOG_FILES'):
            environment.pop(name, None)
    report = {'status': 'running', 'resource': resource, 'case': args.case, 'prefix': str(prefix), 'commands': []}

    def run(argv, *, cwd=None, expected=0):
        command = [str(x) for x in argv]
        completed = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, timeout=240)
        report['commands'].append({'argv': command, 'cwd': str(cwd) if cwd else None,
            'returncode': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr})
        if (expected is None and completed.returncode == 0) or (expected is not None and completed.returncode != expected):
            raise RuntimeError('Unexpected command status: '+command[0])
        return completed

    try:
        profile = json.loads((prefix/'share/compiler-playground'/resource/'profile.json').read_text())
        if (profile['version'] != config['version'] or profile['id'] != resource or
                profile['installed_tests'] != config['installed_tests'] or
                profile['source_ctest_passed'] < config['minimum_ctest_count']):
            raise RuntimeError('Installed profile is absent or mismatched')
        with tempfile.TemporaryDirectory(prefix='cpg-native-check-') as temporary:
            temporary = Path(temporary)
            if args.case == 'upstream':
                report['tests'] = []
                for name in config['installed_tests']:
                    executable = prefix/'libexec'/resource/name
                    command = [executable]
                    cwd = temporary
                    if resource == 'lpm-libexpat-source':
                        command += ['-v']
                    elif resource == 'lpm-libxml2-source':
                        cwd = prefix/'share'/resource/'source'
                        if name == 'runtest':
                            command += ['--out', temporary]
                    else:
                        listed = run([executable, '--gtest_list_tests']).stdout
                        names = []
                        suite = ''
                        for line in listed.splitlines():
                            clean = line.split('#', 1)[0].strip()
                            if not clean:
                                continue
                            if not line.startswith(' ') and clean.endswith('.'):
                                suite = clean
                            elif line.startswith('  ') and suite:
                                names.append(suite+clean)
                        if not names:
                            raise RuntimeError('Upstream executable lists no actual tests')
                        command += ['--gtest_output=xml:'+str(temporary/(name+'.xml'))]
                    completed = run(command, cwd=cwd)
                    entry = {'executable': name, 'status': 'passed'}
                    if resource == 'lpm-libexpat-source':
                        match = re.search(r'100%: Checks: (\d+), Failed: 0', completed.stdout)
                        passes = re.findall(r'^PASS: ', completed.stdout, re.M)
                        if match is None or int(match[1]) < 100 or len(passes) != int(match[1]):
                            raise RuntimeError('Expat did not execute every reported upstream check')
                        entry['checks_passed'] = int(match[1])
                    elif resource == 'lpm-libxml2-source':
                        if name == 'runtest':
                            match = re.search(r'Total (\d+) tests, no errors', completed.stdout)
                            if match is None or int(match[1]) < 100:
                                raise RuntimeError('libxml2 regression input suite was empty or failed')
                            entry['checks_passed'] = int(match[1])
                        else:
                            entry['scope'] = 'Unmodified self-contained upstream program; exit status checked'
                    else:
                        root = ET.parse(temporary/(name+'.xml')).getroot()
                        cases = root.findall('.//testcase')
                        executed = [case for case in cases if case.get('status') == 'run']
                        observed = {case.get('classname')+'.'+case.get('name') for case in cases}
                        if observed != set(names) or not executed or any(case.find('failure') is not None for case in cases):
                            raise RuntimeError('GTest XML differs from the actual listed tests')
                        skipped = sum(case.find('skipped') is not None for case in executed)
                        entry.update(listed=len(names), executed=len(executed), passed=len(executed)-skipped,
                            skipped=skipped, disabled=len(cases)-len(executed))
                        if entry['passed'] < 1:
                            raise RuntimeError('No upstream test passed')
                    report['tests'].append(entry)
            else:
                report['consumers'] = []
                for kind in ('shared', 'static'):
                    executable = temporary/('consumer-'+kind)
                    suffix = '.so' if kind == 'shared' else '.a'
                    libraries = [prefix/'lib'/('lib'+name+suffix) for name in config['libraries']]
                    run(['/usr/bin/'+config['compiler'], '-O2', '-std='+config['standard'],
                        '-I'+str(prefix/'include'/config['include_suffix']),
                        Path(__file__).with_name(config['consumer']), *libraries,
                        '-Wl,-rpath,'+str(prefix/'lib'), '-pthread', '-ldl', '-lm', '-o', executable])
                    arguments = ['--gtest_output=xml:'+str(temporary/(kind+'.xml'))] if resource == 'lpm-googletest-source' else []
                    completed = run([executable, *arguments])
                    if resource == 'lpm-googletest-source':
                        root = ET.parse(temporary/(kind+'.xml')).getroot()
                        if int(root.get('tests','0')) != 3 or int(root.get('failures','1')) != 0:
                            raise RuntimeError('Fresh GoogleTest/GoogleMock consumer did not run its three tests')
                        failed = run([executable, '--cpg-fail'], expected=1)
                        if '[  FAILED  ]' not in failed.stdout:
                            raise RuntimeError('Deliberately failing assertion had no test failure diagnostic')
                        result = {'tests_passed': 3, 'intentional_failure_rejected': True}
                    else:
                        result = json.loads(completed.stdout)
                        if result.get('version') != config['version'] or result.get('checks',0) < 10 or result.get('invalid_inputs_rejected') != 3:
                            raise RuntimeError('Fresh XML consumer returned incomplete numerical results')
                    links = run(['/usr/bin/ldd', executable]).stdout
                    if 'not found' in links:
                        raise RuntimeError('Consumer has an unresolved dynamic dependency')
                    for name in config['libraries']:
                        lines = [line for line in links.splitlines() if 'lib'+name+'.so' in line]
                        if kind == 'shared' and (len(lines) != 1 or str(prefix/'lib')+'/' not in lines[0]):
                            raise RuntimeError('Consumer resolved another prefix for '+name)
                        if kind == 'static' and lines:
                            raise RuntimeError('Static consumer unexpectedly uses a shared resource library')
                    report['consumers'].append({'link': kind, 'result': result})
                if resource == 'lpm-libexpat-source':
                    valid, invalid = temporary/'valid.xml', temporary/'invalid.xml'
                    valid.write_text('<root><child>ok</child></root>'); invalid.write_text('<root>')
                    run([prefix/'bin/xmlwf', valid]); run([prefix/'bin/xmlwf', invalid], expected=None)
                    report['cli'] = 'valid document accepted; incomplete document rejected'
                elif resource == 'lpm-libxml2-source':
                    tool = prefix/'bin/xml2-config'
                    if Path(run([tool, '--prefix']).stdout.strip()).resolve() != prefix:
                        raise RuntimeError('xml2-config resolves another installation prefix')
                    if run([tool, '--version']).stdout.strip() != config['version']:
                        raise RuntimeError('xml2-config version differs from the installed library')
                    flags = shlex.split(run([tool, '--cflags', '--libs']).stdout)
                    consumer = temporary/'xml2-config-consumer'
                    run(['/usr/bin/gcc', '-std=c99', '-O2', Path(__file__).with_name(config['consumer']),
                        *flags, '-Wl,-rpath,'+str(prefix/'lib'), '-o', consumer])
                    if json.loads(run([consumer]).stdout).get('invalid_inputs_rejected') != 3:
                        raise RuntimeError('xml2-config consumer omitted malformed-input checks')
                    links = run(['/usr/bin/ldd', consumer]).stdout
                    matching = [line for line in links.splitlines() if 'libxml2.so' in line]
                    if len(matching) != 1 or str(prefix/'lib')+'/' not in matching[0]:
                        raise RuntimeError('xml2-config consumer links another installation')
                    report['xml2_config'] = {'status':'passed', 'resolved_prefix':str(prefix), 'consumer':'passed'}
                    valid, invalid = temporary/'valid.xml', temporary/'invalid.xml'
                    valid.write_text('<root><n>42</n></root>'); invalid.write_text('<root>')
                    if run([prefix/'bin/xmllint', '--xpath', 'string(/root/n)', valid]).stdout.strip() != '42':
                        raise RuntimeError('xmllint XPath returned the wrong value')
                    run([prefix/'bin/xmllint', '--nonet', invalid], expected=None)
                    report['cli'] = 'known XPath answer; incomplete document rejected'
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
