#!/usr/bin/env python3
"""Build the fixed Honggfuzz source with its exact private header/library inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from private_debs import extract, sha
from archive_material import create as create_archive_material


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'prefix'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, required=True)
    args = parser.parse_args()
    need(1 <= args.jobs <= 2, 'This profile allows at most two build jobs')
    source, build, prefix = args.source.resolve(), args.build.resolve(), args.prefix.resolve()
    recipe = Path(__file__).resolve().parent
    config = json.loads((recipe / 'config.json').read_text())
    share = prefix / 'share/honggfuzz'
    share.mkdir(parents=True)
    logs = build / 'build-evidence'
    logs.mkdir(parents=True)
    runtime = share / 'runtime'
    closure = extract(recipe, config['recipe_inputs'], runtime, share / 'inputs', logs / 'private-deb-extraction')
    write(logs / 'private-deb-closure.json', closure)
    work = build / 'native-source-copy'
    shutil.copytree(source, work, symlinks=True)
    patch = config['source_patch']
    patched = work / patch['path']
    need(sha(patched) == patch['before_sha256'], 'The input C source differs from the reviewed patch base')
    text = patched.read_text()
    need(text.count(patch['before']) == 1, 'The source patch is ambiguous')
    patched.write_text(text.replace(patch['before'], patch['after']))
    need(sha(patched) == patch['after_sha256'], 'The explicit source patch produced different bytes')
    write(logs / 'applied-source-patch.json', patch)
    library = runtime / 'usr/lib/x86_64-linux-gnu'
    need(library.is_dir(), 'Fixed private library directory is missing')
    loaders = [p for p in runtime.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
    need(len(loaders) == 1, 'Expected one exact private dynamic loader')
    loader = loaders[0]
    env = dict(os.environ, PATH='/usr/bin:/bin', LC_ALL='C.UTF-8', PYTHONDONTWRITEBYTECODE='1', CC='/usr/bin/gcc', AR='/usr/bin/ar')
    for variable in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'CPPFLAGS', 'CXXFLAGS'):
        env.pop(variable, None)
    env['CFLAGS'] = '-O2 -mtune=generic -funroll-loops -I' + str(runtime / 'usr/include') + ' -I' + str(runtime / 'usr/include/x86_64-linux-gnu')
    env['LDFLAGS'] = '-L' + str(library) + ' -Wl,-rpath-link,' + str(library)
    env['HFUZZ_INC'] = '/nonexistent-cpg-honggfuzz-source'
    env['BUILD_LINUX_NO_BFD'] = 'false'
    env['BUILD_OSSFUZZ_STATIC'] = 'false'
    for path in ('/usr/include/intel-pt.h', '/usr/local/include/intel-pt.h'):
        need(not Path(path).exists(), 'An undeclared host Intel PT header would change this profile')
    commands = []

    def command(label, argv, *, cwd=work, timeout=1200):
        argv = list(map(str, argv))
        with (logs / (label + '.stdout')).open('wb') as out, (logs / (label + '.stderr')).open('wb') as err:
            result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout)
        commands.append({'label': label, 'argv': argv, 'cwd': str(cwd), 'returncode': result.returncode,
                         'stdout': label + '.stdout', 'stderr': label + '.stderr'})
        write(logs / 'commands.json', commands)
        need(result.returncode == 0, 'Build command failed: ' + label)
        return (logs / (label + '.stdout')).read_text(errors='replace')

    observed_tools = {}
    for name, executable in (('cc', '/usr/bin/gcc'), ('cxx', '/usr/bin/g++'), ('make', '/usr/bin/make'), ('ar', '/usr/bin/ar'), ('python', '/usr/bin/python3')):
        observed_tools[name] = {'path': executable, 'resolved_path': str(Path(executable).resolve()),
                                'sha256': sha(Path(executable).resolve()),
                                'version_output': command(name + '-version', [executable, '--version'])}
    command('make-all', ['/usr/bin/make', '-j' + str(args.jobs)])
    stage = build / 'upstream-install'
    command('make-install', ['/usr/bin/make', '-j' + str(args.jobs), 'PREFIX=' + str(stage), 'install'])
    need((work / 'honggfuzz').read_bytes()[:4] == b'\x7fELF', 'The fuzzer was not compiled to a native ELF executable')
    bindir, libexec, libdir = prefix / 'bin', prefix / 'libexec', prefix / 'lib'
    bindir.mkdir();libexec.mkdir();libdir.mkdir()
    shutil.copy2(work / 'honggfuzz', libexec / 'honggfuzz')
    shutil.copy2(work / 'hfuzz_cc/hfuzz-cc', libexec / 'hfuzz-cc')
    for relative in ('libhfuzz/libhfuzz.a', 'libhfuzz/libhfuzz.so', 'libhfcommon/libhfcommon.a', 'libhfnetdriver/libhfnetdriver.a'):
        shutil.copy2(work / relative, libdir / Path(relative).name)
    # The upstream Makefile misspells one installed header directory. Copy its
    # complete unchanged includes tree, preserving the source's actual API path.
    shutil.copytree(source / 'includes', prefix / 'include')
    resolved_libraries = {}
    for binary in ('honggfuzz', 'hfuzz-cc'):
        listing = command(binary + '-private-runtime-list', [loader, '--library-path', library, '--list', libexec / binary])
        resolved = []
        for line in listing.splitlines():
            match = re.search(r'=> (/\S+)\s+\(', line)
            if match:
                path = Path(match[1]).resolve()
                need(path.is_relative_to(runtime), 'A runtime library came from outside the fixed private closure')
                resolved.append({'path': path.relative_to(runtime).as_posix(), 'sha256': sha(path)})
        need(resolved and any(Path(row['path']).name == 'libc.so.6' for row in resolved), 'The exact private libc was not observed')
        resolved_libraries[binary] = resolved
    loader_relative = loader.relative_to(runtime).as_posix()
    library_relative = library.relative_to(runtime).as_posix()
    launcher_prefix = '#!/bin/sh\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nruntime="$root/share/honggfuzz/runtime"\nunset LD_PRELOAD LD_LIBRARY_PATH\n'
    for name in ('honggfuzz', 'hfuzz-cc', 'hfuzz-gcc', 'hfuzz-g++', 'hfuzz-clang', 'hfuzz-clang++'):
        compiler = name != 'honggfuzz'
        body = launcher_prefix
        if compiler:
            body += ('CPG_HFUZZ_INCLUDE="$root/include"\nHFUZZ_LHFUZZ_PATH="$root/lib/libhfuzz.a"\n'
                     'HFUZZ_LHFCOMMON_PATH="$root/lib/libhfcommon.a"\nHFUZZ_LHFNETDRIVER_PATH="$root/lib/libhfnetdriver.a"\n'
                     'export CPG_HFUZZ_INCLUDE HFUZZ_LHFUZZ_PATH HFUZZ_LHFCOMMON_PATH HFUZZ_LHFNETDRIVER_PATH\n')
        target = 'hfuzz-cc' if compiler else 'honggfuzz'
        body += 'exec "$runtime/' + loader_relative + '" --library-path "$runtime/' + library_relative + '" --argv0 "$root/bin/' + name + '" "$root/libexec/' + target + '" "$@"\n'
        (bindir / name).write_text(body);(bindir / name).chmod(0o755)
    # Preserve the exact tar, including links to not-yet-built upstream tools.
    # Such links cannot be admitted as an expanded installed-prefix payload.
    package_root = recipe.parent
    package_manifest = json.loads((package_root / 'manifest.json').read_text())
    source_rows = [row for row in package_manifest['sources'] if row['id'] == 'honggfuzz']
    need(len(source_rows) == 1, 'Expected exactly one Honggfuzz original source archive')
    raw_relative = Path(source_rows[0]['path'])
    need(not raw_relative.is_absolute() and '..' not in raw_relative.parts, 'Invalid original source archive path')
    raw_source = (package_root / raw_relative).resolve(strict=True)
    need(raw_source.is_relative_to(package_root), 'Original source archive is outside the package')
    retained = create_archive_material(raw_source, share / 'source', config['original_source_lock'])
    examples = share / 'upstream-examples'
    examples.mkdir()
    shutil.copy2(source / 'examples/badcode/targets/badcode1.c', examples / 'badcode1.c')
    shutil.copy2(source / 'COPYING', share / 'COPYING')
    for name in ('check.py', 'api_target.c', 'config.json'):
        shutil.copy2(recipe / name, share / name)
    write(share / 'private-deb-closure.json', closure)
    write(share / 'applied-source-patch.json', patch)
    for path in logs.glob('*.json'):
        shutil.copy2(path, share / path.name)
    profile = {'schema_version': 1, 'resource_id': 'honggfuzz', 'configuration': config['configuration'],
        'recipe_inputs': config['recipe_inputs'], 'original_dependencies': config['original_dependencies'],
        'direct_dependency_refinement': {'host_manager_checked': config['host_direct_dependency_scope'],
            'private_exact_deb_closure_for': config['private_direct_dependencies'], 'private_deb_packages': len(config['recipe_inputs']),
            'unrelated_transitive_catalog_toolchain_locks_claimed': False},
        'private_runtime': {'loader': loader_relative, 'loader_sha256': sha(loader), 'library_directory': library_relative,
                            'resolved_libraries': resolved_libraries},
        'source_patch': patch, 'observed_build_tools': observed_tools,
        'original_material': {'representation': retained['representation'], 'archive_sha256': retained['archive']['sha256'],
            'archive_bytes': retained['archive']['bytes'], 'members': len(retained['members']),
            'extracted_source_tree_is_installed': False},
        'upstream_tests': {'automated_test_runner': 'not_present_in_locked_snapshot',
            'upstream_example_selected': 'examples/badcode/targets/badcode1.c',
            'upstream_example_sha256': sha(source / 'examples/badcode/targets/badcode1.c'),
            'execution_scope': 'The installed functional check compiles and runs the original badcode1 example plus a local persistent API target; results belong to each real check receipt'},
        'host_apt_transaction': 'not_run', 'target_instruction_or_hardware_benchmark': 'not_run'}
    write(prefix / 'share/compiler-playground/honggfuzz/profile.json', profile)
    print(json.dumps({'status': 'passed', 'native_build': 'passed', 'private_deb_inputs': len(config['recipe_inputs'])}))


if __name__ == '__main__':
    main()
