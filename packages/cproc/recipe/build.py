#!/usr/bin/env python3
"""Build the original cproc commit with an exact private developer toolchain."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from private_debs import extract, sha

def need(value, message):
    if not value:
        raise RuntimeError(message)

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'prefix', 'qbe-prefix'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    need(1 <= args.jobs <= 2, 'Use one or two build jobs')
    recipe = Path(__file__).resolve().parent
    config = json.loads((recipe / 'config.json').read_text())
    source, build, prefix = args.source.resolve(), args.build.resolve(), args.prefix.resolve()
    qbe = args.qbe_prefix.resolve()
    need((qbe / 'bin/qbe').is_file(), 'The independently managed exact QBE dependency is absent')
    share = prefix / 'share/cproc'
    proof = prefix / 'share/compiler-playground/cproc'
    share.mkdir(parents=True)
    proof.mkdir(parents=True)
    tools = prefix / 'libexec/cproc-tools'
    tools.mkdir(parents=True)
    logs = build / 'build-evidence'
    logs.mkdir(parents=True)
    private = share / 'toolchain'
    closure = extract(recipe, config['recipe_inputs'], private, share / 'inputs', logs / 'decode', config['archival_only_links'])
    # The DEBs target an usr-merged Ubuntu root. A private sysroot must recreate
    # these filesystem aliases explicitly; none points outside this prefix.
    aliases=[]
    for name in ('lib','lib64'):
        destination=private/name
        if not destination.exists() and not destination.is_symlink():
            need((private/'usr'/name).is_dir(), 'Missing usr-merged target '+name)
            destination.symlink_to('usr/'+name)
            aliases.append({'path':name,'target':'usr/'+name,'reason':'Ubuntu usr-merged sysroot alias used by unchanged libc linker scripts'})
    closure['added_sysroot_aliases']=aliases
    write(proof / 'private-deb-closure.json', closure)
    library = private / 'usr/lib/x86_64-linux-gnu'
    gccdir = private / 'usr/lib/gcc/x86_64-linux-gnu/13'
    for path in (library / 'ld-linux-x86-64.so.2', gccdir / 'crtbegin.o', gccdir / 'libgcc.a', private / 'usr/libexec/gcc/x86_64-linux-gnu/13/cc1'):
        need(path.is_file(), 'The fixed private toolchain is incomplete: ' + str(path))
    # All configured stage commands are upstream-supported configure inputs.
    # The tiny stage wrappers bind their arguments to this installation only.
    common = '''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
private="$root/share/cproc/toolchain"
library="$private/usr/lib/x86_64-linux-gnu"
gccdir="$private/usr/lib/gcc/x86_64-linux-gnu/13"
loader="$library/ld-linux-x86-64.so.2"
unset LD_PRELOAD LD_LIBRARY_PATH GCC_EXEC_PREFIX COMPILER_PATH LIBRARY_PATH CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH
'''
    wrappers = {
        'cc1': common + 'exec "$loader" --library-path "$library" "$private/usr/libexec/gcc/x86_64-linux-gnu/13/cc1" "$@"\n',
        'cpg-cpp': common + 'exec "$loader" --library-path "$library" "$private/usr/bin/x86_64-linux-gnu-cpp-13" -B"$root/libexec/cproc-tools/" -nostdinc -isystem "$gccdir/include" -isystem "$private/usr/include/x86_64-linux-gnu" -isystem "$private/usr/include" "$@"\n',
        'cpg-as': common + 'exec "$loader" --library-path "$library" "$private/usr/bin/x86_64-linux-gnu-as" "$@"\n',
        'cpg-ld': common + 'exec "$loader" --library-path "$library" "$private/usr/bin/x86_64-linux-gnu-ld.bfd" --sysroot="$private" -L"$gccdir" -L"$library" "$@" --dynamic-linker "$loader" -rpath "$library"\n',
        'cpg-qbe': common + ': "${CPG_QBE_PREFIX:?Set CPG_QBE_PREFIX to the separately installed exact QBE binary dependency}"\nexec "$CPG_QBE_PREFIX/bin/qbe" "$@"\n',
    }
    for name, body in wrappers.items():
        (tools / name).write_text(body)
        (tools / name).chmod(0o755)
    # GCC searches its -B prefixes for as/ld and cc1; these are ordinary copies,
    # not links to any installation outside this prefix.
    shutil.copy2(tools / 'cpg-as', tools / 'as')
    shutil.copy2(tools / 'cpg-ld', tools / 'ld')
    native = build / 'native-build'
    shutil.copytree(source, native, symlinks=True)
    temporary=build/'temporary';temporary.mkdir()
    env = dict(os.environ)
    env.update(PATH=str(tools) + ':/usr/bin:/bin', CPG_QBE_PREFIX=str(qbe), TMPDIR=str(temporary))
    for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
        env.pop(key, None)
    commands = []
    def run(label, argv, timeout=600):
        argv = [str(a) for a in argv]
        with (logs / (label + '.stdout')).open('wb') as stdout, (logs / (label + '.stderr')).open('wb') as stderr:
            proc = subprocess.run(argv, cwd=native, env=env, stdout=stdout, stderr=stderr, timeout=timeout)
        commands.append({'label':label, 'argv':argv, 'cwd':str(native), 'returncode':proc.returncode,
                         'stdout':label+'.stdout', 'stderr':label+'.stderr'})
        write(logs / 'commands.json', commands)
        need(proc.returncode == 0, 'Build command failed: ' + label)
        return (logs / (label + '.stdout')).read_text()
    # The native driver/front-end are statically linked to the fixed private
    # headers, CRT and libc. This preserves upstream /proc/self/exe behavior.
    cflags = '-O2 -g -std=c99 -fno-pie --sysroot=' + str(private) + ' -B' + str(tools) + '/ -B' + str(gccdir) + '/ -nostdinc -isystem ' + str(gccdir/'include') + ' -isystem ' + str(private/'usr/include/x86_64-linux-gnu') + ' -isystem ' + str(private/'usr/include')
    ldflags = '-static -no-pie --sysroot=' + str(private) + ' -B' + str(tools) + '/ -B' + str(gccdir) + '/'
    run('configure', ['./configure', '--prefix=' + str(prefix), '--target=x86_64-linux-gnu',
        '--with-cpp=cpg-cpp', '--with-qbe=cpg-qbe', '--with-as=cpg-as', '--with-ld=cpg-ld',
        '--with-ldso=', '--with-gcc-libdir=CPG_PRIVATE_GCC_WRAPPER', 'CC=/usr/bin/cc',
        'CFLAGS=' + cflags, 'LDFLAGS=' + ldflags])
    # configure has no option to omit its one GCC -L argument. The private linker
    # wrapper supplies that directory per installation. Adjust only generated
    # config.h, recording both complete versions and exact hashes.
    generated = native / 'config.h'
    before = generated.read_bytes()
    token = b'"-L", "CPG_PRIVATE_GCC_WRAPPER",'
    need(before.count(token) == 1, 'Unexpected upstream generated link configuration')
    after = before.replace(token, b'', 1)
    generated.write_bytes(after)
    (logs / 'config.h.before').write_bytes(before)
    (logs / 'config.h.after').write_bytes(after)
    write(logs / 'generated-config-adaptation.json', {'file':'config.h', 'generated_file_only':True,
        'before_sha256':hashlib.sha256(before).hexdigest(), 'after_sha256':hashlib.sha256(after).hexdigest(),
        'operation':'Remove the unique configure-generated GCC library marker; the private linker stage supplies its absolute installation-specific directory.',
        'original_source_modified':False})
    run('source-compiler-header-origins', ['/usr/bin/cc', *shlex.split(cflags), '-v', '-H', '-E', 'driver.c'])
    header_text=(logs/'source-compiler-header-origins.stdout').read_text()
    header_paths=[m.group(1) for m in re.finditer(r'^#\s+\d+\s+"([^"]+)"',header_text,re.M) if m.group(1).startswith('/')]
    need(header_paths and all(Path(path).resolve().is_relative_to(private) or Path(path).resolve().is_relative_to(native) for path in header_paths), 'Host compiler opened undeclared host headers while building cproc')
    write(logs/'source-compiler-header-origins.json',{'status':'passed','paths':sorted(set(header_paths)), 'compiler_driver':'/usr/bin/cc','private_cc1_wrapper':str(tools/'cc1')})
    run('make', ['/usr/bin/make', '-j' + str(args.jobs)])
    test_output = run('upstream-check', ['/usr/bin/make', 'check'])
    # bootstrap uses the cproc driver, whose private linker produces dynamic
    # test outputs; do not feed host-GCC-only switches to that driver.
    bootstrap_output = run('upstream-bootstrap', ['/usr/bin/make', '-j' + str(args.jobs), 'bootstrap', 'CFLAGS=-O2 -g -std=c99', 'LDFLAGS='])
    stage2_output = run('upstream-check-stage2', ['/usr/bin/make', 'check-stage2'])
    selected_tests=sorted(p.relative_to(native).as_posix() for pattern in ('test/*.c','test/constraint/*.c') for p in native.glob(pattern))
    def tests(label):
        stdout=(logs/(label+'.stdout')).read_text()
        stderr=(logs/(label+'.stderr')).read_text()
        rows=[{'test':m.group(2),'result':m.group(1)} for m in re.finditer(r'^\[(PASS|FAIL)\] (.+)$',stderr,re.M)]
        need(sorted(r['test'] for r in rows)==selected_tests, 'Original upstream test execution list is incomplete: '+label)
        need(all(r['result']=='PASS' for r in rows), 'An original upstream case failed: '+label)
        need(str(len(rows))+'/'+str(len(rows))+' tests passed' in stdout, 'Missing exact upstream execution total')
        need('invalid test' not in stderr, 'Original harness ignored an invalid test')
        return {'command':'make '+('check' if label=='upstream-check' else 'check-stage2'), 'executed':len(rows), 'passed':len(rows),'failed':0,'skipped':0,'cases':rows,'stdout':'build-evidence/'+label+'.stdout','stderr':'build-evidence/'+label+'.stderr'}
    run('install', ['/usr/bin/make', 'install'])
    native_install = prefix / 'libexec/cproc-native'
    native_install.mkdir()
    for name in ('cproc', 'cproc-qbe'):
        shutil.move(prefix / 'bin' / name, native_install / name)
        header = (native_install / name).read_bytes()[:4]
        need(header == b'\x7fELF', 'Expected genuinely compiled native ELF: '+name)
        info = run('readelf-' + name, ['/usr/bin/readelf', '-l', native_install / name])
        need('INTERP' not in info, 'Native installed compiler unexpectedly requires the host interpreter')
    entry = '''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PATH="$root/libexec/cproc-tools:/usr/bin:/bin"
export PATH
'''
    for name in ('cproc', 'cproc-qbe'):
        body = entry
        if name == 'cproc':
            body += ': "${CPG_QBE_PREFIX:?Set CPG_QBE_PREFIX to the exact separately managed QBE dependency}"\n'
        body += 'exec "$root/libexec/cproc-native/' + name + '" "$@"\n'
        (prefix / 'bin' / name).write_text(body)
        (prefix / 'bin' / name).chmod(0o755)
    shutil.copytree(source, share / 'source', symlinks=True)
    for name in ('LICENSE', 'README.md'):
        shutil.copy2(source / name, share / name)
    shutil.copytree(recipe, proof / 'recipe', ignore=shutil.ignore_patterns('inputs', '__pycache__'))
    shutil.copytree(logs, proof / 'build-evidence', symlinks=True)
    profile = dict(config)
    profile.update(status='passed', generated_config_adaptation=json.loads((logs/'generated-config-adaptation.json').read_text()),
        upstream_tests={'stage1':tests('upstream-check'),
            'stage2':tests('upstream-check-stage2'),
            'bootstrap':{'command':'make bootstrap CFLAGS=-O2 -g -std=c99 LDFLAGS=', 'status':'passed',
                'stage2_cproc_sha256':sha(native/'stage2/cproc'), 'stage3_cproc_sha256':sha(native/'stage3/cproc'),
                'stage2_frontend_sha256':sha(native/'stage2/cproc-qbe'), 'stage3_frontend_sha256':sha(native/'stage3/cproc-qbe')},
            'test_sources_unchanged':True, 'scope':'All cases selected by original runtests in the fixed source; no test-source patch.'})
    write(proof / 'profile.json', profile)
    print(json.dumps({'status':'passed','resource':'cproc','original_source_modified':False}))

if __name__ == '__main__':
    main()
