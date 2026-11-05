#!/usr/bin/env python3
"""Prepare the exact complete source archive as static material, without extraction."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from compiler_playground.resource_deploy import acquire_file
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.archive import inventory
from compiler_playground.packages.spec import validate_spec


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def assemble(raw, locks, payload):
    lock = locks['resolved_main_source']
    if raw.is_symlink() or raw.stat().st_size != lock['bytes'] or sha(raw) != lock['sha256']:
        raise ValueError('Original complete archive identity mismatch')
    (payload / 'archives').mkdir(parents=True, exist_ok=False)
    target = payload / 'archives/original-source.tar.gz'
    shutil.copyfile(raw, target)
    target.chmod(0o644)
    if target.stat().st_nlink != 1 or (target.stat().st_dev, target.stat().st_ino) == (raw.stat().st_dev, raw.stat().st_ino):
        raise ValueError('Material archive must be an ordinary independent copy')
    descriptor = {'format': 'cpg-complete-original-source-archive-set-v1',
        'resource_id': locks['resource_id'], 'source_commit': locks['source_commit'],
        'exact_git_tree_sha1': locks['exact_git_tree_sha1'],
        'archive': {'path': 'archives/original-source.tar.gz', 'sha256': lock['sha256'], 'bytes': lock['bytes']},
        'original_regular_files': locks['original_regular_files'],
        'original_symbolic_links': locks['original_symbolic_links'],
        'execution_category': 'archive_set_complete_original_git_tree',
        'expanded_source_tree_deployment': False, 'upstream_execution': False}
    (payload / 'source-set.json').write_text(json.dumps(descriptor, sort_keys=True, indent=2) + '\n')
    (payload / 'source-set.json').chmod(0o644)
    return inventory(payload)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--definition', type=Path, default=Path(__file__).resolve().parents[1] / 'package.json')
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--no-network', action='store_true')
    a = p.parse_args()
    definition, cache = a.definition.resolve().parent, a.cache.resolve()
    spec = validate_spec(json.loads(a.definition.read_text()))
    locks = json.loads((definition / 'recipe/acquisition-locks.json').read_text())
    if locks['original_sources'] != spec['sources']:
        raise ValueError('Original discovery sources changed')
    lock = locks['resolved_main_source']
    for key, value in spec['sources'][0].items():
        if not (value is None and key in ('sha256', 'bytes')) and lock[key] != value:
            raise ValueError('Supplementary lock changed an original source fact')
    item = {'id': lock['id'], 'source_url': lock['url'], 'sha256': lock['sha256'],
            'archive_bytes': lock['bytes'], 'license_class': spec['metadata']['catalog']['license_class']}
    if a.no_network:
        item['bundled_path'] = str(cache / 'sha256' / lock['sha256'][:2] / lock['sha256'])
    receipt = {}
    raw = acquire_file(item, cache, receipt=receipt)
    with tempfile.TemporaryDirectory(prefix='cpg-complete-archive-material-') as temporary:
        payload = Path(temporary) / 'payload'
        rows = assemble(raw, locks, payload)
        expected = json.loads((definition / 'recipe/material-manifest.json').read_text())
        if rows != expected['files']:
            raise ValueError('Complete archive-set inventory differs from the admitted material')
        result = pack(spec, a.output, method='material', payload=payload, recipe_dir=definition / 'recipe',
            provenance={'original_source_lock': lock, 'original_sources_unchanged': True,
                'exact_git_tree_sha1': locks['exact_git_tree_sha1'],
                'execution_category': 'archive_set_complete_original_git_tree',
                'qualification_scope': spec['recipe']['qualification_scope'],
                'source_tree_deployment': False, 'native_execution_qualified': False,
                'dataset_api_qualified': False})
    verify_package(a.output, expected_sha256=result['sha256'], expected_bytes=result['bytes'])
    print(json.dumps({'status': 'passed', 'artifact': result, 'acquisitions': [receipt]}, indent=2))


if __name__ == '__main__':
    main()
