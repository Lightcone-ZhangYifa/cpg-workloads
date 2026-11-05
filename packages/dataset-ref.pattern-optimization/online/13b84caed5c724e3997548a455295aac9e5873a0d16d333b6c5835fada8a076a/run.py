#!/usr/bin/env python3
"""Validate a thin recipe and explicitly prepare its exact CPG material package."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def validate():
    online = json.loads((ROOT/'online.json').read_text())
    expected = {row['path']: row for row in online['recipe_files']}
    actual = {}
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if '__pycache__' in relative.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError('Thin recipe links are not permitted')
        if path.is_file() and relative.as_posix() != 'online.json':
            actual[relative.as_posix()] = path
    if set(actual) != set(expected):
        raise ValueError('Thin recipe file set changed')
    for name, path in actual.items():
        lock = expected[name]
        if path.stat().st_size != lock['bytes'] or sha256(path) != lock['sha256']:
            raise ValueError('Thin recipe file identity changed: ' + name)
    spec = json.loads((ROOT/'package.json').read_text())
    manifest = json.loads((ROOT/'offline-manifest.json').read_text())
    if spec != manifest['package']:
        raise ValueError('Reconstruction definition differs from the qualified offline artifact')
    if spec['id'] != online['resource_id'] or spec['sources'] != online['original_source_locks']:
        raise ValueError('Original resource identity changed')
    if spec['metadata']['catalog'] != online['original_catalog']:
        raise ValueError('Original catalog metadata changed')
    return online

def outside_recipe(path):
    value = path.expanduser().resolve()
    if value == ROOT or ROOT in value.parents:
        raise ValueError('Use a cache/output outside the immutable thin recipe')
    return value

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'prepare'])
    parser.add_argument('--framework-path', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inputs-json', type=Path)
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    online = validate()
    if args.action == 'validate':
        print(json.dumps({'status': 'passed', 'resource_id': online['resource_id'], 'recipe_files_verified': len(online['recipe_files'])}, sort_keys=True))
        return
    if args.cache is None or args.output is None:
        parser.error('prepare requires --cache and --output')
    cache = outside_recipe(args.cache)
    output = outside_recipe(args.output)
    if output.exists():
        raise FileExistsError('Use a fresh output artifact')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    if args.framework_path:
        source = args.framework_path.expanduser().resolve() / 'src'
        if not (source/'compiler_playground').is_dir():
            raise ValueError('--framework-path must contain src/compiler_playground')
        env['PYTHONPATH'] = str(source)
    command = [sys.executable, '-B', str(ROOT/'recipe/prepare.py'), '--cache', str(cache), '--output', str(output)]
    if args.inputs_json:
        command += ['--inputs-json', str(args.inputs_json.expanduser().resolve())]
    if args.no_network:
        command.append('--no-network')
    process = subprocess.run(command, env=env, text=True, capture_output=True)
    if process.returncode:
        sys.stderr.write(process.stderr)
        raise SystemExit(process.returncode)
    result = json.loads(process.stdout)
    lock = online['offline_artifact']
    actual = result['artifact']
    for key in ['sha256', 'bytes', 'manifest_sha256', 'method']:
        if actual[key] != lock[key]:
            raise ValueError('Prepared artifact differs from qualified offline identity: ' + key)
    if output.stat().st_size != lock['bytes'] or sha256(output) != lock['sha256']:
        raise ValueError('Prepared artifact changed after framework verification')
    result['thin_recipe_verified'] = True
    result['exact_offline_artifact_identity_verified'] = True
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))

if __name__ == '__main__':
    main()
