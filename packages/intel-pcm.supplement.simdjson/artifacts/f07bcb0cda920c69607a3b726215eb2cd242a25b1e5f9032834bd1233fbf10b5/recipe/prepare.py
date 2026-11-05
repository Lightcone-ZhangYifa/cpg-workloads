#!/usr/bin/env python3
"""Acquire the declared complete original input and reproduce this material package."""
import argparse, json, pathlib, shutil, tempfile
from compiler_playground.resource_deploy import acquire_file, unpack_archive
from compiler_playground.packages import pack, verify_package
from compiler_playground.packages.spec import validate_spec
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--definition',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[1]/'package.json')
    p.add_argument('--cache',type=pathlib.Path,required=True)
    p.add_argument('--output',type=pathlib.Path,required=True)
    p.add_argument('--source-file',type=pathlib.Path)
    p.add_argument('--no-network',action='store_true')
    a=p.parse_args(); spec=validate_spec(json.loads(a.definition.read_text())); lock=spec['sources'][0]
    item={'id':lock['id'],'source_url':lock['url'],'sha256':lock['sha256'],'archive_bytes':lock['bytes'],'license_class':spec['metadata']['catalog']['license_class']}
    if a.source_file: item['bundled_path']=str(a.source_file.resolve())
    elif a.no_network: item['bundled_path']=str(a.cache/'sha256'/lock['sha256'][:2]/lock['sha256'])
    receipt={}; raw=acquire_file(item,a.cache,receipt=receipt)
    with tempfile.TemporaryDirectory(prefix='cpg-material-replay-') as tmp:
        payload=pathlib.Path(tmp)/'payload'
        if spec['recipe']['material_layout']=='expanded_original_archive':
            unpack_archive(raw,payload,strip_root=lock['strip_root'])
        else:
            target=payload/lock['material_path']; target.parent.mkdir(parents=True); shutil.copyfile(raw,target); target.chmod(0o644)
        root=a.definition.parent
        result=pack(spec,a.output,method='material',payload=payload,recipe_dir=root/'recipe',tools_dir=root/'tools' if (root/'tools').is_dir() else None,provenance={'original_source_lock':lock,'qualification_scope':spec['recipe']['qualification_scope'],'original_catalog_unchanged':True,'native_execution_qualified':False,'live_origin_qualified':False})
    verify_package(a.output,expected_sha256=result['sha256'],expected_bytes=result['bytes'])
    print(json.dumps({'status':'passed','artifact':result,'acquisition':receipt},indent=2))
if __name__=='__main__': main()
