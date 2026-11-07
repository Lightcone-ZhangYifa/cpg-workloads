"""Prepare the pinned, offline runtime of one worker104 resource.

The prefix contains immutable archives. Every consumer gets a fresh runtime
directory, so compiler caches, generated files and proof outputs are not shared.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def unpack(path, output, kind, strip=0):
    output.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path) as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if kind == 'rust':
                if len(parts) < 3 or parts[2] not in ('bin', 'lib', 'libexec'):
                    continue
                parts = parts[2:]
            else:
                parts = parts[strip:]
            if not parts:
                continue
            if any(part == '..' for part in parts) or PurePosixPath(*parts).is_absolute():
                raise ValueError('Unsafe archive path')
            member.name = str(PurePosixPath(*parts))
            archive.extract(member, output, filter='data')


def prepare(prefix, output, *, include_source_build=False):
    prefix, output = Path(prefix).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Runtime output must be a fresh directory')
    lock = json.loads((prefix / 'input-lock.json').read_text())
    for row in lock['files']:
        file = prefix / row['path']
        if file.stat().st_size != row['bytes'] or sha256(file) != row['sha256']:
            raise ValueError('Input identity mismatch: ' + row['path'])
    output.mkdir(parents=True)
    for row in lock['files']:
        runtime = row.get('runtime')
        if include_source_build and row.get('purpose') == 'source-build-cargo':
            runtime = {'kind': 'rust', 'destination': 'rust'}
        if not runtime:
            continue
        source = prefix / row['path']
        target = output / runtime['destination']
        if runtime['kind'] == 'file':
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            target.chmod(0o755)
        else:
            unpack(source, target, runtime['kind'], runtime.get('strip', 0))
    env = {key: value for key, value in os.environ.items() if not key.startswith('LD_')}
    env.update(LC_ALL='C', CARGO_HOME=str(output / 'cargo-home'),
               RUSTUP_HOME=str(output / 'rustup-home'), RUSTUP_AUTO_INSTALL='0',
               CARGO_NET_OFFLINE='true', CARGO_BUILD_JOBS='1',
               CARGO_INCREMENTAL='0', PYTHONDONTWRITEBYTECODE='1',
               TMPDIR=str(output / 'tmp'))
    (output / 'tmp').mkdir()
    env['PATH'] = str(output / 'rust/bin') + os.pathsep + env.get('PATH', '')
    libraries = [output / 'rust/lib']
    profile = lock['profile']
    if profile == 'rustsmith':
        libraries += [output / 'java/lib', output / 'java/lib/server']
    if profile == 'aeneas':
        libraries += [output / 'coq/usr/lib/x86_64-linux-gnu',
                      output / 'coq/usr/lib/ocaml/stublibs']
    env['LD_LIBRARY_PATH'] = os.pathsep.join(str(path) for path in libraries)
    if profile == 'aeneas':
        coq = output / 'coq/usr'
        config = output / 'findlib.conf'
        config.write_text('path="' + str(coq / 'lib/ocaml') + '"\n')
        env.update(CHARON_TOOLCHAIN_IS_IN_PATH='1',
                   COQLIB=str(coq / 'lib/ocaml/coq'),
                   COQCORELIB=str(coq / 'lib/ocaml/coq-core'),
                   OCAMLPATH=str(coq / 'lib/ocaml'),
                   OCAMLFIND_CONF=str(config),
                   CAML_LD_LIBRARY_PATH=str(coq / 'lib/ocaml/stublibs'),
                   OCAMLRUNPARAM='s=256k,o=20,O=60')
    if profile == 'rustlantis':
        (output / 'bin/rustc').symlink_to('rustup')
        env['PATH'] = str(output / 'bin') + os.pathsep + env['PATH']
    # Compressed input files must not hide the original CPG ELF/ABI gate.
    # Scan the complete expanded runtime with the same actual environment used
    # by every tool below, before executing any packaged ELF.
    from compiler_playground.packages.compatibility import check_binary_runtime
    from compiler_playground.packages.manager import current_target
    compatibility_file = output.parent / 'native-runtime-compatibility.json'
    compatibility = {'status': 'running', 'actual_target': current_target(),
        'original_manager_modified': False, 'expanded_runtime': str(output),
        'declared_runtime_environment': {'PATH': env['PATH'], 'LD_LIBRARY_PATH': env['LD_LIBRARY_PATH']},
        'ignored_ambient_loader_variables': sorted(key for key in os.environ if key.startswith('LD_')),
        'native_runtime_compatibility': []}
    try:
        check_binary_runtime(output, actual_target=compatibility['actual_target'],
                             environment=env, evidence=compatibility['native_runtime_compatibility'])
        if not compatibility['native_runtime_compatibility']:
            raise RuntimeError('No actual ELF files were checked')
        compatibility['status'] = 'passed'
    except BaseException as error:
        compatibility.update(status='failed', error=str(error))
        raise
    finally:
        compatibility_file.write_text(json.dumps(compatibility, indent=2) + '\n')
    if profile == 'rustlantis':
        subprocess.run([str(output / 'bin/rustup'), 'toolchain', 'link',
                        'cpg-pinned', str(output / 'rust')],
                       env=env, check=True, capture_output=True)
    return {'prefix': prefix, 'root': output, 'env': env, 'lock': lock,
            'native_runtime_compatibility': compatibility_file}


def command(runtime, tool, arguments):
    root, prefix = runtime['root'], runtime['prefix']
    programs = {
        'rustc': root / 'rust/bin/rustc',
        'charon': root / 'aeneas/charon',
        'aeneas': root / 'aeneas/aeneas',
        'coqc': root / 'coq/usr/bin/coqc',
        'coqchk': root / 'coq/usr/bin/coqchk',
        'generate': root / 'bin/generate',
        'difftest': root / 'bin/difftest',
    }
    if tool == 'rustsmith':
        return [str(root / 'java/bin/java'), '-Xmx384m', '-XX:-UsePerfData',
                '-Djava.io.tmpdir=' + str(root / 'tmp'), '-jar',
                str(prefix / 'inputs/rustsmith.jar'), *arguments]
    if tool not in programs or not programs[tool].is_file():
        raise ValueError('Tool is not included in this resource: ' + tool)
    return [str(programs[tool]), *arguments]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('tool')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runtime = prepare(args.prefix, args.runtime)
    result = subprocess.run(command(runtime, args.tool, args.arguments), env=runtime['env'])
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
