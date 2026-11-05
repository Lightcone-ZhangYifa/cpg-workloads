#!/usr/bin/env python3
"""Build the exact XED-to-XML fork and preserve all original source inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'prefix'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, required=True)
    args = parser.parse_args()
    need(1 <= args.jobs <= 2, 'This profile permits at most two build jobs')
    source, build, prefix = args.source.resolve(), args.build.resolve(), args.prefix.resolve()
    recipe = Path(__file__).resolve().parent
    config = json.loads((recipe / 'config.json').read_text())
    logs = build / 'build-evidence'
    logs.mkdir(parents=True)
    commands = []
    env = dict(os.environ, PATH='/usr/bin:/bin', PYTHONDONTWRITEBYTECODE='1', LC_ALL='C.UTF-8')
    for variable in ('PYTHONPATH', 'PYTHONHOME', 'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
        env.pop(variable, None)

    def command(label, argv, *, cwd=build, timeout=1800, defer_status=False):
        argv = [str(x) for x in argv]
        with (logs / (label + '.stdout')).open('wb') as out, (logs / (label + '.stderr')).open('wb') as err:
            result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout)
        row = {'label': label, 'argv': argv, 'cwd': str(cwd), 'returncode': result.returncode,
               'stdout': label + '.stdout', 'stderr': label + '.stderr'}
        commands.append(row)
        write(logs / 'commands.json', commands)
        if not defer_status:
            need(result.returncode == 0, 'Command failed: ' + label)
        return (logs / (label + '.stdout')).read_text(errors='replace')

    work = build / 'work'
    work.mkdir()
    xed = work / 'xed'
    shutil.copytree(source, xed, symlinks=True)
    from adapt_fixtures import apply
    adaptation = apply(xed, recipe / 'fixture-format-adaptation.json')
    write(logs / 'fixture-adaptation.json', adaptation)
    private_python = build / 'private-build-python'
    private_python.mkdir()
    inputs = []
    for item in config['recipe_inputs']:
        raw = recipe / item['filename']
        need(raw.is_file() and raw.stat().st_size == item['bytes'] and sha(raw) == item['sha256'], 'Recipe input identity differs: ' + item['id'])
        if item['kind'] == 'source_archive':
            with tarfile.open(raw) as archive:
                roots = {m.name.split('/')[0] for m in archive.getmembers()}
                need(len(roots) == 1, 'Expected a single archive root for mbuild')
                archive.extractall(work, filter='data')
                (work / roots.pop()).rename(work / 'mbuild')
        elif item['kind'] == 'precompiled_build_dependency':
            observed = command(item['id'] + '-control', ['/usr/bin/dpkg-deb', '--field', raw, 'Package', 'Version', 'Architecture'])
            fields = dict(line.split(': ', 1) for line in observed.splitlines())
            need(fields == {'Package': item['package_name'], 'Version': item['version'], 'Architecture': 'all'}, 'Fixed Debian metadata differs')
            command(item['id'] + '-extract', ['/usr/bin/dpkg-deb', '--extract', raw, private_python])
        else:
            raise ValueError('Unexpected recipe input kind')
        inputs.append(item)
    env['PYTHONPATH'] = str(private_python / 'usr/lib/python3/dist-packages')
    observed_tools = {}
    for name, executable in (('cc', '/usr/bin/gcc'), ('cxx', '/usr/bin/g++'), ('python', '/usr/bin/python3')):
        observed_tools[name] = {'path': executable, 'resolved_path': str(Path(executable).resolve()),
                                'sha256': sha(Path(executable).resolve()),
                                'version_output': command(name + '-version', [executable, '--version'])}
    origins = command('private-setuptools-origin', ['/usr/bin/python3', '-B', '-c',
        'import json,setuptools,pkg_resources; print(json.dumps({"setuptools":setuptools.__file__,"pkg_resources":pkg_resources.__file__}))'])
    for path in json.loads(origins).values():
        need(Path(path).resolve().is_relative_to(private_python), 'Build module escaped the fixed private inputs')
    # The upstream installer deletes its destination before creating a kit.
    # Stage it separately, then copy into the package-manager-owned prefix.
    install_stage = build / 'upstream-install'
    argv = ['/usr/bin/python3', '-B', 'mfile.py', '--jobs=' + str(args.jobs), '--opt=2',
            '--cc=/usr/bin/gcc', '--cxx=/usr/bin/g++', '--install-dir=' + str(install_stage), 'install', 'test']
    build_stdout = command('upstream-build-install-test', argv, cwd=xed, timeout=2400, defer_status=True)
    test_log = xed / 'obj/TEST.OUT.txt'
    need(test_log.is_file(), 'Upstream did not emit its real test execution log')
    shutil.copy2(test_log, logs / 'upstream-canned-tests.log')
    need(commands[-1]['returncode'] == 0 and build_stdout.count('[XED CMDLINE TEST] passed') == 1,
         'The complete upstream build/decoder/canned-test command did not pass')
    text = test_log.read_text(errors='replace')
    counts = {}
    for key in ('TESTS', 'TESTED', 'SKIPPED', 'ERRORS'):
        values = re.findall(r'^\[' + key + r'\]\s+(\d+)\s*$', text, re.M)
        need(len(values) == 1, 'Expected one real upstream test counter: ' + key)
        counts[key.lower()] = int(values[0])
    observed_tests = re.findall(r'^\[TESTING\]\s+(.+?)\s*$', text, re.M)
    completed = len(re.findall(r'^Retcode\s+-?\d+\s*$', text, re.M))
    skipped = text.count('[SKIPPING DUE TO TEST SUBSET RESTRICTION]')
    need(counts['tests'] == len(observed_tests) and counts['tested'] == completed > 0,
         'Printed counters do not equal actual completed command records')
    need(counts['errors'] == 0 and counts['skipped'] == skipped and completed + skipped == len(observed_tests),
         'Upstream reported failure or inconsistent execution accounting')
    test_rows = []
    sections = {part.splitlines()[0].split(' ', 1)[1]: part
                for part in re.split(r'(?=\[TESTING\])', text) if part.startswith('[TESTING]')}
    for name in observed_tests:
        directory = (xed / name).resolve()
        need(directory.is_relative_to(xed / 'tests'), 'An upstream test escaped the source copy')
        rel = directory.relative_to(xed).as_posix()
        section = sections[name]
        status = 'skipped_by_upstream_code_selection' if '[SKIPPING DUE TO TEST SUBSET RESTRICTION]' in section else 'executed'
        returns = re.findall(r'^Retcode\s+(-?\d+)\s*$', section, re.M)
        need((status == 'executed' and len(returns) == 1) or (status != 'executed' and not returns),
             'Per-test actual command records differ from selected status')
        test_rows.append({'path': rel, 'command': (directory / 'cmd').read_text().strip(),
                          'status': status, 'actual_returncode': int(returns[0]) if returns else None,
                          'inputs': {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size}
                                     for p in sorted(directory.iterdir()) if p.is_file()}})
    expected_dirs = ['tests-base', 'tests-knc', 'tests-avx512', 'tests-xop', 'tests-syntax', 'tests-cet']
    expected = {p.parent.relative_to(xed).as_posix() for d in expected_dirs for p in (xed / 'tests' / d).glob('test-*/cmd')}
    need({r['path'] for r in test_rows} == expected, 'The default upstream test set changed')
    write(logs / 'upstream-test-inventory.json', {'status': 'passed', 'test_driver_sha256': sha(xed / 'tests/run-cmd.py'),
        'test_selection_source_sha256': sha(xed / 'xed_mbuild.py'), 'counts': counts, 'tests': test_rows,
        'excluded_test_directories': ['tests-avx512pf', 'tests-via'],
        'excluded_reason': 'Not selected by the unchanged upstream default test driver, retained in original source'})
    cmdline_log = xed / 'obj/CMDLINE.OUT.txt'
    need(cmdline_log.is_file(), 'The upstream decoder command-line test did not execute')
    shutil.copy2(cmdline_log, logs / 'upstream-commandline.log')
    xml = xed / 'instructions.xml'
    need(xml.is_file(), 'The locked XED fork did not generate its ISA XML')
    root = ET.parse(xml).getroot()
    instruction_count = sum(1 for _ in root.iter('instruction'))
    need(root.tag == 'root' and instruction_count > 1000, 'Generated ISA XML is missing its instruction records')
    shutil.copytree(install_stage, prefix, dirs_exist_ok=True, symlinks=True)
    material = prefix / 'share/uica.supplement.xed'
    material.mkdir(parents=True)
    shutil.copytree(source, material / 'source', symlinks=True)
    # Supplement code is preserved separately; the raw archive remains intact.
    shutil.copytree(work / 'mbuild', material / 'mbuild-source', symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (material / 'inputs').mkdir()
    for item in inputs:
        shutil.copy2(recipe / item['filename'], material / 'inputs' / Path(item['filename']).name)
    shutil.copy2(xml, material / 'instructions.xml')
    for name in ('check.py', 'api_probe.c'):
        shutil.copy2(recipe / name, material / name)
    for filename in ('upstream-canned-tests.log', 'upstream-commandline.log', 'upstream-test-inventory.json', 'commands.json', 'fixture-adaptation.json'):
        shutil.copy2(logs / filename, material / filename)
    profile = {'schema_version': 1, 'resource_id': 'uica.supplement.xed', 'recipe_inputs': inputs,
        'configuration': {'upstream_commit': config['upstream_commit'], 'mbuild_commit': config['mbuild_commit'],
            'compiler_options': argv[3:], 'encoder': True, 'decoder': True, 'python_extension': False,
            'target': config['target'], 'host_toolchain_scope': 'Observed executable identities; no claim of the complete catalog APT compiler/Python closure'},
        'observed_build_tools': observed_tools,
        'upstream_tests': {'status': 'passed', **counts, 'canned_commands_executed': completed,
            'fixture_format_adaptation': adaptation,
            'commandline_decoder_executed': 1, 'test_inventory_sha256': sha(logs / 'upstream-test-inventory.json'),
            'test_log_sha256': sha(logs / 'upstream-canned-tests.log')},
        'generated_isa_xml': {'sha256': sha(xml), 'bytes': xml.stat().st_size, 'instructions': instruction_count,
            'origin': 'Generated from the fixed XED instruction tables; not uops.info measurement data'},
        'scope_exclusions': ['uiCA simulator and uops.info measured XML', 'Python extension ABI', 'hardware execution of decoded ISA variants', 'OCI and performance benchmarks'],
        'host_apt_transaction': 'not_run'}
    write(prefix / 'share/compiler-playground/uica.supplement.xed/profile.json', profile)
    print(json.dumps({'status': 'passed', 'canned_tests_executed': completed, 'generated_instruction_records': instruction_count}))


if __name__ == '__main__':
    main()
