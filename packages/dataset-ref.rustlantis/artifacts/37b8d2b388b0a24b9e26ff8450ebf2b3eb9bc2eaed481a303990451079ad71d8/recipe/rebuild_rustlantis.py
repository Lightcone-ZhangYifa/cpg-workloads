"""Rebuild the original pinned Rustlantis source without network access.

The installed CPG prefix is immutable. Sources, vendor files, compiler state and
build outputs are created below one fresh output directory, never in the prefix.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import subprocess
import time


def rebuild(prefix, output):
    prefix, output = Path(prefix).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('cpg_runtime', prefix / 'cpg_resource_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = module.prepare(prefix, output / 'runtime', include_source_build=True)
    lock = runtime['lock']
    if lock['profile'] != 'rustlantis':
        raise ValueError('This source rebuild recipe is for Rustlantis only')
    module.unpack(prefix / 'inputs/rustlantis.tar.gz', output / 'source', 'tar', strip=1)
    module.unpack(prefix / 'inputs/rustlantis-vendor.tar.gz', output / 'vendor', 'tar', strip=1)
    source = output / 'source'
    config = source / '.cargo/config.toml'
    config.parent.mkdir(exist_ok=True)
    config.write_text('[source.crates-io]\nreplace-with = "vendored-sources"\n'
                      '[source.vendored-sources]\ndirectory = ' + json.dumps(str(output / 'vendor')) + '\n')
    env = runtime['env'].copy()
    env.update(CARGO_PROFILE_DEV_DEBUG='0', CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='1',
               CARGO_NET_OFFLINE='true', CARGO_TARGET_DIR=str(output / 'target'))
    # Direct compiler/cargo avoid any ambient rustup override.
    env['RUSTC'] = str(output / 'runtime/rust/bin/rustc')
    before = module.sha256(source / 'Cargo.lock')
    command = [str(output / 'runtime/rust/bin/cargo'), 'build', '--locked', '--offline',
               '-j', '1', '-p', 'generate', '-p', 'difftest']
    start = time.monotonic()
    try:
        process = subprocess.run(command, cwd=source, env=env, capture_output=True,
                                 text=True, timeout=1200)
        returncode, stdout, stderr, timed_out = process.returncode, process.stdout, process.stderr, False
    except subprocess.TimeoutExpired as error:
        def decode(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
        returncode, stdout, stderr, timed_out = 124, decode(error.stdout), decode(error.stderr), True
    record = {'native_runtime_compatibility': json.loads(runtime['native_runtime_compatibility'].read_text()),
              'argv': command, 'returncode': returncode, 'timed_out': timed_out,
              'stdout': stdout, 'stderr': stderr,
              'seconds': time.monotonic() - start,
              'cargo_lock_before': before, 'cargo_lock_after': module.sha256(source / 'Cargo.lock')}
    (output / 'source-build-result.json').write_text(json.dumps(record, indent=2) + '\n')
    if returncode != 0:
        raise RuntimeError('Pinned offline source build failed: ' + stderr)
    if record['cargo_lock_before'] != record['cargo_lock_after']:
        raise RuntimeError('Locked source build changed Cargo.lock')
    for name in ('generate', 'difftest'):
        file = output / 'target/debug' / name
        if not file.is_file():
            raise RuntimeError('Missing compiled binary: ' + name)
    record['status'] = 'passed'
    record['scope'] = 'Original source and Cargo.lock compiled with fully vendored dependencies; binary byte identity across build paths is not claimed.'
    (output / 'source-build-result.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.prefix, args.output)))
