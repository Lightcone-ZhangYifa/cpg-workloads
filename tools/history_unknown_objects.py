#!/usr/bin/env python3
"""Hash and identify previously unmapped content-named historical ZIP members."""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile
from import_archives import safe_relative, sniff, write_json


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lineage',type=Path,required=True)
    p.add_argument('--ledger',type=Path,required=True);p.add_argument('--history-root',type=Path,required=True)
    p.add_argument('--framework-root',type=Path,required=True);p.add_argument('--scratch',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();history=a.history_root.resolve()
    if any(x.resolve().is_relative_to(history) for x in (a.output,a.scratch)):p.error('Output must be outside historical input')
    sys.path.insert(0,str(a.framework_root.resolve()/'src'))
    from compiler_playground.packages import verify_package
    ledger=json.loads(a.ledger.read_text());lineage=json.loads(a.lineage.read_text())
    if lineage['inventory_sha256']!=ledger['inventory_sha256']:p.error('Inventory identities differ')
    if a.output.exists():p.error('Output exists; inspect before another pass')
    spec=importlib.util.spec_from_file_location('history_inventory',a.framework_root/'tools/history-inventory.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    files={x['path']:x for x in ledger['files']};bynames={Path(x['path']).name:x for x in ledger['files']};families={x['family']:x for x in ledger['split_families']};verified_sources={}
    output={'schema_version':1,'inventory_sha256':ledger['inventory_sha256'],'cases':[],
            'scope':'SHA-256 and size of each selected member checked. Headers are format leads only; no workload execution or functional qualification.'}
    a.scratch.mkdir(parents=True,exist_ok=True)
    for row in lineage['occurrences']:
        if row['binding']!='unmapped':continue
        case={'source':row['source'],'member':row['member'],'sha256_from_name':row['sha256_from_name'],'bytes':row['bytes'],'status':'started'}
        output['cases'].append(case);write_json(a.output,output)
        try:
            source=row['source']
            if source not in verified_sources:
                parts=[files[source]] if row['kind']=='file' else [bynames[x] for x in families[source]['parts']]
                paths=[]
                for part in parts:
                    path=history.joinpath(*safe_relative(part['path']).parts);digest=hashlib.sha256();n=0
                    with path.open('rb') as f:
                        for b in iter(lambda:f.read(1024*1024),b''):digest.update(b);n+=len(b)
                    if digest.hexdigest()!=part['sha256'] or n!=part['bytes']:raise ValueError('Outer source identity changed')
                    paths.append(path)
                verified_sources[source]=paths
            paths=verified_sources[source];zsource=paths[0] if row['kind']=='file' else mod.PartsReader(paths)
            with zipfile.ZipFile(zsource) as z:
                info=z.getinfo(row['member']);h=hashlib.sha256();n=0;head=b''
                with z.open(info) as f:
                    for b in iter(lambda:f.read(1024*1024),b''):
                        if len(head)<4096:head=(head+b)[:4096]
                        h.update(b);n+=len(b)
                if h.hexdigest()!=row['sha256_from_name'] or n!=row['bytes']:raise ValueError('Member SHA-256 or size differs from its name')
                case.update(member_sha256_verified=True,header_hex=head[:16].hex())
                if head.startswith(b'\x1f\x8b'):
                    with z.open(info) as stream:kind=sniff(stream)
                    if kind=='package':
                        with tempfile.TemporaryDirectory(prefix='unknown-package-',dir=a.scratch) as td:
                            local=Path(td)/'member.cpgpkg'
                            with z.open(info) as source_stream,local.open('xb') as target:shutil.copyfileobj(source_stream,target)
                            checked=verify_package(local);m=checked['manifest'];case.update(format='cpg_package',id=m['package']['id'],method=m['method'],manifest_sha256=m['manifest_sha256'])
                    else:
                        try:
                            with z.open(info) as source_stream:
                                with gzip.GzipFile(fileobj=source_stream) as gz:unpacked=gz.read(512)
                            case['format']='gzip_tar_header' if unpacked[257:262]==b'ustar' else 'gzip_other_or_partial_header'
                        except (OSError,EOFError) as error:case.update(format='gzip_header_error',format_error=type(error).__name__+': '+str(error))
                elif head.startswith(b'PK\x03\x04'):case['format']='zip_header'
                elif head.startswith(b'\x7fELF'):case['format']='elf_header'
                elif head.startswith(b'SQLite format 3\x00'):case['format']='sqlite_header'
                elif head.startswith(b'PACK'):case['format']='git_pack_header'
                elif head.startswith(b'%PDF-'):case['format']='pdf_header'
                elif head.startswith(b'\xfd7zXZ\x00'):case['format']='xz_header'
                else:
                    try:
                        text=head.decode('utf-8');case['format']='json_or_jsonl_text' if text.lstrip().startswith(('{','[')) else 'text_header'
                    except UnicodeDecodeError:case['format']='unidentified_binary_header'
                case['status']='verified_member_format_identified'
        except Exception as e:case.update(status='error',error=type(e).__name__+': '+str(e))
        write_json(a.output,output);print(json.dumps({'source':case['source'],'status':case['status'],'format':case.get('format')}),flush=True)
    print(json.dumps({'cases':len(output['cases']),'status':dict(Counter(x['status'] for x in output['cases'])),
                      'formats':dict(Counter(x.get('format','unknown') for x in output['cases']))}),flush=True)

if __name__=='__main__':main()
