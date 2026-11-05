#!/usr/bin/env python3
"""Acquire the exact original single file and pack it with the existing CPG API."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition', type=Path, default=Path(__file__).resolve().parents[1]/'package.json')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-file', type=Path, help='An existing exact original file; its full lock is still checked.')
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    from compiler_playground.packages import pack, verify_package
    from compiler_playground.packages.spec import validate_spec
    from compiler_playground.resource_deploy import acquire_file
    spec = validate_spec(json.loads(args.definition.read_text()))
    if spec['provider'] != 'material' or len(spec['sources']) != 1:
        raise ValueError('This recipe requires exactly one original material source')
    lock = spec['sources'][0]
    if lock['extract'] or not lock['sha256'] or type(lock['bytes']) is not int:
        raise ValueError('This recipe requires a fully locked, non-archive original file')
    raw = {'id': lock['id'], 'source_url': lock['url'], 'sha256': lock['sha256'],
           'archive_bytes': lock['bytes'], 'license_class': spec['metadata']['catalog']['license_class']}
    if args.source_file is not None:
        raw['bundled_path'] = str(args.source_file.absolute())
    elif args.no_network:
        # A missing cache remains a missing local input; no URL fallback occurs.
        raw['bundled_path'] = str((args.cache/'sha256'/lock['sha256'][:2]/lock['sha256']).absolute())
    acquisition = {}
    source = acquire_file(raw, args.cache, receipt=acquisition)
    with tempfile.TemporaryDirectory(prefix='cpg-static-material-') as temporary:
        payload = Path(temporary)/'payload'
        destination = payload/lock['material_path']
        destination.parent.mkdir(parents=True)
        for directory in (payload, *[p for p in destination.parents if p != payload and payload in p.parents]):
            directory.chmod(0o755)
        shutil.copy2(source, destination)
        destination.chmod(0o644)
        result = pack(spec, args.output, method='material', payload=payload,
            recipe_dir=args.definition.parent/'recipe',
            provenance={'qualification_scope': 'complete_original_single_file_static_material_only',
                'original_source_lock': lock, 'native_execution': False, 'oci_execution': False})
        verify_package(args.output, expected_sha256=result['sha256'], expected_bytes=result['bytes'])
    print(json.dumps({'status': 'passed', 'resource_id': spec['id'], 'artifact': result,
                      'acquisition': acquisition}, indent=2))


if __name__ == '__main__':
    main()
