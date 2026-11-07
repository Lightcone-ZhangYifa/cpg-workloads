#!/usr/bin/env python3
"""Validate historical compressed TAR streams without extracting or executing members."""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tarfile

from import_archives import safe_relative, write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger',type=Path,required=True);p.add_argument('--disposition',type=Path,required=True)
    p.add_argument('--history-root',type=Path,required=True);p.add_argument('--framework-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();history=a.history_root.resolve()
    if a.output.resolve().is_relative_to(history):p.error('Output must be outside historical input')
    ledger=json.loads(a.ledger.read_text());disp=json.loads(a.disposition.read_text())
    if ledger['inventory_sha256']!=disp['inventory_sha256']:p.error('Inventory identities differ')
    if a.output.exists():
        output=json.loads(a.output.read_text())
        if output['inventory_sha256']!=ledger['inventory_sha256']:p.error('Output inventory identity differs')
    else:output={'schema_version':1,'inventory_sha256':ledger['inventory_sha256'],'streams':{}}
    spec=importlib.util.spec_from_file_location('history_inventory',a.framework_root/'tools/history-inventory.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    byname={Path(x['path']).name:x for x in ledger['files']};bypath={x['path']:x for x in ledger['files']};jobs=[]
    for f in ledger['split_families']:
        if not f.get('zip_index_key'):jobs.append((f['family'],[byname[n] for n in f['parts']]))
    for row in disp['files']:
        if row['disposition']=='unclassified_file_pending' and row['path'].lower().endswith('.tar.gz'):
            jobs.append((row['path'],[bypath[row['path']]]))
    for name,parts in jobs:
        if name in output['streams']:continue
        paths=[history.joinpath(*safe_relative(x['path']).parts) for x in parts];combined=hashlib.sha256();total=0
        result={'parts':[x['path'] for x in parts],'status':'started'};output['streams'][name]=result;write_json(a.output,output)
        try:
            for path,row in zip(paths,parts):
                h=hashlib.sha256();n=0
                with path.open('rb') as inp:
                    for block in iter(lambda:inp.read(1024*1024),b''):h.update(block);combined.update(block);n+=len(block);total+=len(block)
                if n!=row['bytes'] or h.hexdigest()!=row['sha256']:raise ValueError('Part SHA-256 or size differs')
            result.update(bytes=total,sha256=combined.hexdigest(),parts_sha256_verified=True)
            with paths[0].open('rb') as f:magic=f.read(8)
            result['magic_hex']=magic.hex()
            if not magic.startswith(b'\x1f\x8b'):
                result.update(status='non_gzip_stream_identified',reason='Part bytes verified; terminal completeness and function are not established.')
            else:
                stream=module.PartsReader(paths);names=set();duplicates=0;unsafe=0;kinds=Counter();logical=0;count=0
                with gzip.GzipFile(fileobj=stream) as gz:
                    with tarfile.open(fileobj=gz,mode='r|') as archive:
                        for member in archive:
                            count+=1;logical+=member.size;kinds[member.type.decode('latin-1')]+=1
                            if member.name in names:duplicates+=1
                            names.add(member.name)
                            path=PurePosixPath(member.name)
                            if path.is_absolute() or '..' in path.parts or '\\' in member.name:unsafe+=1
                    while gz.read(1024*1024):pass
                result.update(status='gzip_tar_stream_read',tar_members=count,logical_bytes=logical,
                    duplicate_names=duplicates,unsafe_paths=unsafe,member_kinds=dict(kinds),
                    scope='TAR stream and gzip footer read; no extraction, execution, installation or functional qualification.')
        except Exception as e:result.update(status='stream_error',error=type(e).__name__+': '+str(e))
        write_json(a.output,output);print(json.dumps({'source':name,'status':result['status']}),flush=True)

if __name__=='__main__':main()
