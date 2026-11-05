#!/usr/bin/env python3
"""Preparation only: preserve exact Ubuntu corresponding source and signatures."""
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
PACKAGES = [('dwarfutils', '20210528-1build2', 'universe/d/dwarfutils')]

def fetch(url,path,expected=None,size=None):
    if not path.exists():
        for attempt in range(1,5):
            try:
                with urllib.request.urlopen(url,timeout=120) as response: data=response.read()
                path.write_bytes(data)
                break
            except Exception as exc:
                print('attempt',attempt,url,type(exc).__name__,str(exc),flush=True)
                if attempt==4: raise
                time.sleep(attempt)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and digest!=expected: raise ValueError('source digest mismatch: '+path.name)
    if size is not None and path.stat().st_size!=size: raise ValueError('source size mismatch: '+path.name)
    print(path.name,digest,path.stat().st_size,flush=True)
    return {'url':url,'path':path.relative_to(ROOT).as_posix(),'sha256':digest,'bytes':path.stat().st_size,
        'dsc_checksum_verified':expected is not None}

def main():
    destination=ROOT/'inputs/source';destination.mkdir(exist_ok=True)
    items=[]
    for name,version,pool in PACKAGES:
        base='https://archive.ubuntu.com/ubuntu/pool/'+pool+'/'
        dsc=f'{name}_{version}.dsc'
        locked=json.loads((ROOT/'metadata/sources.lock.json').read_text())
        expected_dsc=next(row for group in locked['source_sets'] for row in group['files'] if row['path']=='inputs/source/'+dsc)
        records=[fetch(base+dsc,destination/dsc,expected_dsc['sha256'],expected_dsc['bytes'])]
        records[0]['dsc_checksum_verified']=False
        text=(destination/dsc).read_text()
        section=re.search(r'^Checksums-Sha256:\n((?: .+\n)+)',text,re.M)
        if not section: raise ValueError('No source SHA256 section: '+dsc)
        for line in section.group(1).splitlines():
            digest,size,filename=line.split()
            records.append(fetch(base+filename,destination/filename,digest,int(size)))
        items.append({'source_package':name,'version':version,'files':records})
    (ROOT/'metadata/sources.lock.json').write_text(json.dumps({'schema_version':1,'source_sets':items},indent=2)+'\n')

if __name__=='__main__': main()
