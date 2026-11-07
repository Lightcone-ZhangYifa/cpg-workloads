#!/usr/bin/env python3
"""Compile pinned upstream ORC examples and an external-symbol JITLink probe.

Only local LLVM 23.1.4 SDK inputs are accepted. No download operation is present.
The SDK's original libraries are not rebuilt by this bounded capability check.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import time


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sdk', type=Path, required=True)
    p.add_argument('--examples', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cxx', default='g++')
    p.add_argument('--zstd-library', type=Path)
    p.add_argument('--xml2-library', type=Path)
    a = p.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        p.error('This recorded execution profile requires Linux x86_64.')
    sdk, examples, out = a.sdk.resolve(), a.examples.resolve(), a.output.absolute()
    if out.exists():
        p.error('Output must be a new independent directory.')
    out.mkdir(parents=True)
    (out / 'bin').mkdir()
    (out / 'logs').mkdir()
    events = []
    env = dict(os.environ, LC_ALL='C', LANG='C', PYTHONDONTWRITEBYTECODE='1')

    def run(argv, label, expected=None):
        argv = [str(x) for x in argv]
        start = time.monotonic()
        r = subprocess.run(argv, cwd=out, env=env, capture_output=True,
                           text=True, timeout=600)
        (out / 'logs' / (label+'.stdout')).write_text(r.stdout)
        (out / 'logs' / (label+'.stderr')).write_text(r.stderr)
        events.append({'label': label, 'argv': argv, 'returncode': r.returncode,
                       'seconds': time.monotonic()-start,
                       'stdout': 'logs/'+label+'.stdout',
                       'stderr': 'logs/'+label+'.stderr'})
        (out / 'commands.json').write_text(json.dumps(events, indent=2)+'\n')
        if r.returncode or expected is not None and expected not in r.stdout:
            raise RuntimeError(label+': '+r.stderr[-2000:]+r.stdout[-2000:])
        return r.stdout

    config = sdk / 'bin/llvm-config'
    version = run([config, '--version'], 'llvm-version').strip()
    if version != '23.1.4':
        raise ValueError('SDK version differs from the frozen LLVM identity')
    flags = shlex.split(run([config, '--cxxflags'], 'cxxflags'))
    link = shlex.split(run([config, '--ldflags', '--libs', 'orcjit', 'jitlink',
                           'native', '--system-libs'], 'linkflags'))
    system_bindings = []
    for option, old in [(a.zstd_library, 'libzstd.a'),
                        (a.xml2_library, '-lxml2')]:
        if option is None:
            continue
        lib = option.resolve(strict=True)
        if not lib.is_file():
            raise ValueError('System library binding is not a regular file')
        matched = [i for i, v in enumerate(link)
                   if v == old or Path(v).name == old]
        if len(matched) != 1:
            raise ValueError('Expected one explicit link flag for '+old)
        link[matched[0]] = str(lib)
        system_bindings.append({'original_flag': old, 'path': str(lib),
                                'sha256': sha(lib), 'bytes': lib.stat().st_size})
    probes = [
        ('LLJITWithCustomObjectLinkingLayer',
         examples/'LLJITWithCustomObjectLinkingLayer/LLJITWithCustomObjectLinkingLayer.cpp',
         'add1(42) = 43'),
        ('LLJITWithSymbolAliases',
         examples/'LLJITWithSymbolAliases/LLJITWithSymbolAliases.cpp',
         'aliased_bar() = 7'),
        ('cpg-orc-jitlink', Path(__file__).resolve().parent/'fixtures/cpg_orc_jitlink.cpp',
         'ORC_JITLINK_PASS cases=2001 host_calls=2001'),
    ]
    inputs = []
    for name, source, expected in probes:
        inputs.append({'path': str(source), 'sha256': sha(source)})
        run([a.cxx, *flags, '-O2', source, '-o', out/'bin'/name, *link],
            'compile-'+name)
        run([out/'bin'/name], 'execute-'+name, expected)
    (out/'report.json').write_text(json.dumps({
        'schema_version': 1, 'status': 'passed', 'llvm_version': version,
        'llvm_commit': '7a941dfb2877a0b8cf30323fefa85ad019e0b0f5',
        'profile': 'official prebuilt SDK; original examples compiled locally',
        'full_llvm_source_build': False, 'network_used': False,
        'host': platform.platform(), 'compiler': shutil.which(a.cxx),
        'explicit_system_library_bindings': system_bindings,
        'source_inputs': inputs, 'commands': events,
        'checks': {'upstream_custom_object_layer': True, 'upstream_symbol_aliases': True,
                   'explicit_jitlink_external_symbol_cases': 2001,
                   'missing_symbol_rejected': True, 'removed_symbol_absent': True},
    }, indent=2)+'\n')
    print('ORC_JITLINK_PROFILE_PASSED')


if __name__ == '__main__':
    main()
