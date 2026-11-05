#!/usr/bin/env python3
"""Preserve an entire originally declared archive through the existing CPG API.

This profile deliberately installs the exact original archive file. It neither
extracts nor executes upstream content and makes no claim about external suites.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from compiler_playground.resource_deploy import acquire_file
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.archive import inventory
from compiler_playground.packages.spec import validate_spec


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition',type=Path,default=Path(__file__).resolve().parents[1]/'package.json')
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--no-network',action='store_true')
    args=parser.parse_args()
    definition=args.definition.resolve().parent
    spec=validate_spec(json.loads(args.definition.read_text()))
    locks=json.loads((definition/'recipe/acquisition-locks.json').read_text())
    if spec['sources']!=locks['original_sources'] or len(spec['sources'])!=1 or spec['sources'][0]['extract'] is not False:
        raise ValueError('This original archive profile requires an explicitly unexpanded source contract')
    source=locks['resolved_main_source']
    if source!=spec['sources'][0] or locks['lfs_objects'] or locks['additional_acquisition_locks']:
        raise ValueError('Original declared archive identity cannot change')
    item={'id':source['id'],'source_url':source['url'],'sha256':source['sha256'],
          'archive_bytes':source['bytes'],'license_class':spec['metadata']['catalog']['license_class']}
    cache=args.cache.resolve()
    if args.no_network:
        item['bundled_path']=str(cache/'sha256'/source['sha256'][:2]/source['sha256'])
    receipt={}
    raw=acquire_file(item,cache,receipt=receipt)
    raw=cache/'sha256'/source['sha256'][:2]/source['sha256']
    if raw.is_symlink() or raw.stat().st_size!=source['bytes'] or sha(raw)!=source['sha256']:
        raise ValueError('Original archive full identity mismatch')
    relative=PurePosixPath(source['material_path'])
    if relative.is_absolute() or '..' in relative.parts or relative.as_posix()!=source['material_path'] or '\\' in source['material_path']:
        raise ValueError('Unsafe original material path')
    with tempfile.TemporaryDirectory(prefix='cpg-declared-archive-material-') as temp:
        payload=Path(temp)/'payload';payload.mkdir()
        target=payload/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(raw,target);target.chmod(0o644)
        if target.stat().st_nlink!=1 or (target.stat().st_dev,target.stat().st_ino)==(raw.stat().st_dev,raw.stat().st_ino):
            raise ValueError('Material archive copy must own an independent ordinary inode')
        expected=json.loads((definition/'recipe/material-manifest.json').read_text())
        if inventory(payload)!=expected['files']:
            raise ValueError('Declared complete archive inventory changed')
        result=pack(spec,args.output,method='material',payload=payload,recipe_dir=definition/'recipe',
            provenance={'original_source_lock':source,'original_sources_unchanged':True,
                'execution_category':'complete_original_declared_archive_material_only',
                'qualification_scope':spec['recipe']['qualification_scope'],
                'expanded_source_tree_qualified':False,'external_suites_acquired':False,
                'native_execution_qualified':False,'dataset_api_qualified':False})
    verify_package(args.output,expected_sha256=result['sha256'],expected_bytes=result['bytes'])
    print(json.dumps({'status':'passed','resource_id':spec['id'],'artifact':result,'acquisitions':[receipt]},indent=2))


if __name__=='__main__':
    main()
