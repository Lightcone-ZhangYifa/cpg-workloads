#!/usr/bin/env python3
"""Reconstruct the exact original RAJAPerf recursive source material."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from compiler_playground.resource_deploy import acquire_file, unpack_archive
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.archive import inventory
from compiler_playground.packages.spec import validate_spec

def assemble(definition, cache, output, no_network=True, source_file=None):
    specification=validate_spec(json.loads(definition.read_text()))
    closure=json.loads((definition.parent/'recipe/source-closure-locks.json').read_text())
    root=closure['nodes'][closure['root']]
    original=specification['sources'][0]
    assert (root['sha256'],root['bytes'],root['url'])==(original['sha256'],original['bytes'],original['url'])
    receipts=[];mounts=[]
    def acquire(lock, source=None):
        item={'id':'rajaperf-source-closure','source_url':lock['url'],'sha256':lock['sha256'],
              'archive_bytes':lock['bytes'],'license_class':'open'}
        if source is not None:item['bundled_path']=str(source)
        elif no_network:item['bundled_path']=str(cache/'sha256'/lock['sha256'][:2]/lock['sha256'])
        receipt={};raw=acquire_file(item,cache,receipt=receipt);receipts.append(receipt)
        return raw
    def mount(key,destination,ancestry):
        assert key not in ancestry,'Recursive source Gitlink cycle'
        node=closure['nodes'][key]
        raw=acquire(node,source_file if key==closure['root'] else None)
        if destination.exists():
            assert destination.is_dir() and not destination.is_symlink() and not list(destination.iterdir())
            destination.rmdir()
        unpack_archive(raw,destination,strip_root=True)
        mounts.append({'node':key,'path':str(destination.relative_to(output)),'archive_sha256':node['sha256']})
        for extra in closure['extra_files'].get(key,[]):
            relative=PurePosixPath(extra['path']);assert not relative.is_absolute() and '..' not in relative.parts
            target=destination/relative
            assert not os.path.lexists(target),'Supplement would replace an original archive member'
            raw_extra=acquire(extra);target.parent.mkdir(parents=True,exist_ok=True)
            with raw_extra.open('rb') as source,target.open('xb') as out:shutil.copyfileobj(source,out)
            target.chmod(extra['mode'])
            data=target.read_bytes()
            assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==extra['git_blob_sha1']
        for edge in closure['edges']:
            if edge['parent']==key:
                relative=PurePosixPath(edge['path']);assert not relative.is_absolute() and '..' not in relative.parts
                mount(edge['child'],destination/relative,ancestry+[key])
    assert not os.path.lexists(output)
    mount(closure['root'],output,[])
    files=inventory(output)
    for row in files:
        target=output/row['path']
        if row['kind']=='file':assert target.stat().st_nlink==1
        elif row['kind']=='symlink':assert target.resolve().is_relative_to(output.resolve()) and target.resolve().exists()
    return {'status':'passed','acquisitions':receipts,'mounts':mounts,'files':files}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--definition',type=Path,default=Path(__file__).resolve().parents[1]/'package.json')
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-file',type=Path)
    parser.add_argument('--no-network',action='store_true')
    args=parser.parse_args();definition=args.definition.resolve();spec=validate_spec(json.loads(definition.read_text()))
    with tempfile.TemporaryDirectory(prefix='cpg-rajaperf-closure-') as temporary:
        result=assemble(definition,args.cache.resolve(),Path(temporary)/'payload',args.no_network,args.source_file)
        expected=json.loads((definition.parent/'recipe/material-manifest.json').read_text())
        assert result['files']==expected['files'],'Reconstructed recursive source inventory differs'
        closure=(definition.parent/'recipe/source-closure-locks.json').read_bytes()
        artifact=pack(spec,args.output,method='material',payload=Path(temporary)/'payload',recipe_dir=definition.parent/'recipe',
            provenance={'original_source_lock':spec['sources'][0],
                        'source_closure_sha256':hashlib.sha256(closure).hexdigest(),
                        'qualification_scope':spec['recipe']['qualification_scope'],
                        'original_catalog_unchanged':True,'native_execution_qualified':False})
    verify_package(args.output,expected_sha256=artifact['sha256'],expected_bytes=artifact['bytes'])
    print(json.dumps({'status':'passed','artifact':artifact,'acquisitions':result['acquisitions'],'mounts':result['mounts']}))

if __name__=='__main__':main()
