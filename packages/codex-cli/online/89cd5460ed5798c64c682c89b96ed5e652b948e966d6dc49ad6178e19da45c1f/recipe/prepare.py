#!/usr/bin/env python3
"""Package the complete fixed upstream native bundle via the original CPG API.

This is a reproducible upstream binary-bundle preparation, not a source build.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from compiler_playground.resource_deploy import acquire_file, unpack_archive
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.archive import inventory
from compiler_playground.packages.spec import validate_spec


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition',type=Path,default=Path(__file__).resolve().parents[1]/'package.json')
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--no-network',action='store_true')
    args=parser.parse_args()
    spec=validate_spec(json.loads(args.definition.read_text()));root=args.definition.resolve().parent
    locks=json.loads((root/'recipe/acquisition-locks.json').read_text())
    source=locks['resolved_main_source']
    if spec['id']!='codex-cli' or spec['sources']!=locks['original_sources'] or [source]!=spec['sources']:
        raise ValueError('Original native bundle source identity changed')
    item={'id':source['id'],'source_url':source['url'],'sha256':source['sha256'],
          'archive_bytes':source['bytes'],'license_class':spec['metadata']['catalog']['license_class']}
    cache=args.cache.resolve()
    if args.no_network:item['bundled_path']=str(cache/'sha256'/source['sha256'][:2]/source['sha256'])
    receipt={};acquire_file(item,cache,receipt=receipt)
    raw=cache/'sha256'/source['sha256'][:2]/source['sha256']
    with tempfile.TemporaryDirectory(prefix='cpg-codex-bundle-prepare-') as temp:
        payload=Path(temp)/'payload';unpack_archive(raw,payload,strip_root=source['strip_root'])
        expected=json.loads((root/'recipe/bundle-manifest.json').read_text())
        if inventory(payload)!=expected['files']:raise ValueError('Complete original native bundle layout changed')
        result=pack(spec,args.output,method='binary',payload=payload,recipe_dir=root/'recipe',relocatable=True,
            provenance={'original_source_lock':source,'original_native_bundle_retained_complete':True,
                'execution_category':'upstream_precompiled_native_bundle_local_cli_only',
                'qualification_scope':spec['recipe']['qualification_scope'],
                'native_source_compiled':False,'cloud_account_qualified':False,
                'remote_agent_tasks_executed':False,'voice_or_code_mode_companion_executed':False})
    verify_package(args.output,expected_sha256=result['sha256'],expected_bytes=result['bytes'])
    print(json.dumps({'status':'passed','resource_id':'codex-cli','artifact':result,'acquisitions':[receipt]},indent=2))


if __name__=='__main__':main()
