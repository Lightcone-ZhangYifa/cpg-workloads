#!/usr/bin/env python3
"""Exercise an explicitly selected installed Z3 CLI and a fresh C++ API consumer."""
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
    parser.add_argument('--build', type=Path)
    parser.add_argument('--case', choices=('api', 'cli'), required=True)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    prefix = args.prefix.resolve(strict=True)
    environment = dict(os.environ, LC_ALL='C')
    for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'LIBRARY_PATH', 'CPATH',
                 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'Z3_LIB_DIR', 'Z3_LIBRARY_PATH'):
        environment.pop(name, None)
    report = {'status': 'running', 'resource': 'z3', 'case': args.case,
              'prefix': str(prefix), 'commands': []}
    working_directory = None

    def run(argv, *, text_input=None, expected=0):
        if working_directory is None:
            raise RuntimeError('A disposable command working directory is required')
        command = [str(x) for x in argv]
        result = subprocess.run(command, input=text_input, env=environment,
                                cwd=working_directory, capture_output=True, text=True, timeout=120)
        report['commands'].append({'argv': command, 'input': text_input,
                                  'cwd': str(working_directory),
                                  'returncode': result.returncode,
                                  'stdout': result.stdout, 'stderr': result.stderr})
        if ((expected is None and result.returncode == 0) or
                (expected is not None and result.returncode != expected)):
            raise RuntimeError('Unexpected process status for ' + command[0])
        return result

    try:
        profile = json.loads((prefix/'share/compiler-playground/z3/profile.json').read_text())
        if (profile['id'] != 'z3' or profile['version'] != config['version'] or
                profile['upstream_tests']['passed_groups'] != config['upstream_groups']):
            raise RuntimeError('Installed qualification profile differs from this recipe')
        with tempfile.TemporaryDirectory(prefix='cpg-z3-functional-') as temporary:
            temporary = Path(temporary)
            working_directory = temporary
            version = run([prefix/'bin/z3', '-version']).stdout
            if not version.startswith('Z3 version ' + config['version'] + ' '):
                raise RuntimeError('Actual Z3 executable version differs from the immutable source')
            if args.case == 'api':
                executable = temporary/'consumer'
                run(['/usr/bin/g++', '-std=c++20', '-O2',
                     '-I'+str(prefix/'include'), Path(__file__).with_name('consumer.cpp'),
                     prefix/'lib/libz3.so', '-Wl,-rpath,'+str(prefix/'lib'),
                     '-pthread', '-o', executable])
                data = json.loads(run([executable]).stdout)
                if data != {'checks': 8, 'invalid_inputs_rejected': 3,
                            'version': config['version'], 'status': 'passed'}:
                    raise RuntimeError('C++ consumer returned incomplete functional results')
                links = run(['/usr/bin/ldd', executable]).stdout
                matches = [match.group(1) for line in links.splitlines()
                    if (match := re.match(r'^\s*libz3\.so\S*\s+=>\s+(\S+)\s+\(', line))]
                expected_library = (prefix/'lib/libz3.so').resolve(strict=True)
                if (len(matches) != 1 or 'not found' in links
                        or expected_library.parent != (prefix/'lib').resolve(strict=True)
                        or Path(matches[0]).resolve(strict=True) != expected_library):
                    raise RuntimeError('Fresh consumer resolved a different Z3 library')
                report['api'] = data
            else:
                cases = [
                    ('integer-incremental-model',
                     '(set-option :produce-models true)\n(declare-const x Int)\n'
                     '(assert (= x 42))\n(check-sat)\n(get-value (x))\n'
                     '(push)\n(assert (not (= x 42)))\n(check-sat)\n'
                     '(pop)\n(check-sat)\n', ['sat', '((x 42))', 'unsat', 'sat']),
                    ('integer-no-between',
                     '(declare-const x Int)\n(assert (> x 2))\n(assert (< x 3))\n(check-sat)\n', ['unsat']),
                    ('bit-vector-wrap',
                     '(assert (not (= (bvadd #xff #x01) #x00)))\n(check-sat)\n', ['unsat']),
                    ('array-store-select',
                     '(declare-const a (Array Int Int))\n'
                     '(assert (not (= (select (store a 7 42) 7) 42)))\n(check-sat)\n', ['unsat']),
                    ('floating-point-zero',
                     '(assert (not (fp.eq (fp.add RNE (_ +zero 8 24) (_ +zero 8 24)) '
                     '(_ +zero 8 24))))\n(check-sat)\n', ['unsat']),
                    ('quantified-identity',
                     '(assert (forall ((x Int)) (= (+ x 0) x)))\n(check-sat)\n', ['sat']),
                ]
                report['cli_cases'] = []
                for name, query, expected in cases:
                    result = run([prefix/'bin/z3', '-in', '-smt2'], text_input=query)
                    if result.stdout.strip().splitlines() != expected:
                        raise RuntimeError('Known-answer CLI oracle failed: ' + name)
                    report['cli_cases'].append({'name': name, 'status': 'passed', 'expected': expected})
                report['negative_controls'] = []
                for name, query in [
                    ('bitvector-width-mismatch', '(assert (= #b1 #b10))\n'),
                    ('malformed-syntax', '(assert (+\n'),
                    ('undeclared-symbol', '(assert cpg_definitely_missing_bool_symbol)\n'),
                ]:
                    result = run([prefix/'bin/z3', '-in', '-smt2'], text_input=query, expected=None)
                    if 'error' not in (result.stdout+result.stderr).lower():
                        raise RuntimeError('Malformed query had no error diagnostic')
                    report['negative_controls'].append({'name': name, 'status': 'rejected'})
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
