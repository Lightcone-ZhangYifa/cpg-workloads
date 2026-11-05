#!/usr/bin/env python3
"""Produce the exact source-supplement material using the existing CPG APIs."""
from __future__ import annotations
import argparse,json,tempfile
from pathlib import Path
from compiler_playground.packages import pack, verify_package
from compiler_playground.resource_deploy import acquire_file,unpack_archive
from compiler_playground.packages.spec import validate_spec

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--definition',type=Path,default=Path(__file__).resolve().parents[1]/'package.json')
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-file',type=Path)
    p.add_argument('--no-network',action='store_true')
    a=p.parse_args();spec=validate_spec(json.loads(a.definition.read_text())); lock=spec['sources'][0]
    assert lock['id']==spec['id'] and lock['extract'] and lock['sha256'] and isinstance(lock['bytes'],int)
    item={'id':lock['id'],'source_url':lock['url'],'sha256':lock['sha256'],'archive_bytes':lock['bytes'],'license_class':spec['metadata']['catalog']['license_class']}
    if a.source_file: item['bundled_path']=str(a.source_file.resolve())
    elif a.no_network: item['bundled_path']=str(a.cache/'sha256'/lock['sha256'][:2]/lock['sha256'])
    receipt={}; original=acquire_file(item,a.cache,receipt=receipt)
    with tempfile.TemporaryDirectory(prefix='cpg-DejaGNU-material-') as temp:
        payload=Path(temp)/'payload';unpack_archive(original,payload,strip_root=lock['strip_root'])
        result=pack(spec,a.output,method='material',payload=payload,recipe_dir=a.definition.parent/'recipe',provenance={'original_source_lock':lock,'qualification':'complete_declared_upstream_archive_material_only','physical_dejagnu_harness':False,'external_reference_closure':False})
    verify_package(a.output,expected_sha256=result['sha256'],expected_bytes=result['bytes'])
    print(json.dumps({'status':'passed','artifact':result,'acquisition':receipt},indent=2))
if __name__=='__main__':main()
