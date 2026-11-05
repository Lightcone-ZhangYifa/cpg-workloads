#!/usr/bin/env python3
"""Preparation only: fetch explicitly pinned Ubuntu binary inputs, never install."""
import hashlib
import json
import time
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ITEMS = [('libunwind-dev', '1.6.2-3build1.1', 'main/libu/libunwind', 'ede507c1da4f00f439fffd5e4dd08bda541331385fc949d6b67008a804649e8d'), ('libunwind8', '1.6.2-3build1.1', 'main/libu/libunwind', '825cb8724bb6b3389587e30c03ab3381f56a2422cafe3b1945f37e055c65e942')]

def main():
    raw=ROOT/'inputs/deb'
    raw.mkdir(parents=True, exist_ok=True)
    records=[]
    for name,version,pool,expected in ITEMS:
        filename=f'{name}_{version}_amd64.deb'
        url=f'https://archive.ubuntu.com/ubuntu/pool/{pool}/{filename}'
        path=raw/filename
        if not path.exists():
            for attempt in range(1,5):
                try:
                    request=urllib.request.Request(url, headers={'User-Agent':'CPG-cpg_example/1.0'})
                    with urllib.request.urlopen(request,timeout=90) as response:
                        data=response.read()
                    path.write_bytes(data)
                    break
                except Exception as exc:
                    print(f'Fetch attempt {attempt}: {filename}: {type(exc).__name__}: {exc}',flush=True)
                    if attempt == 4: raise
                    time.sleep(attempt)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if expected and digest != expected:
            raise ValueError(f'Original frozen SHA256 mismatch: {filename} {digest} != {expected}')
        records.append({'name':name,'version':version,'architecture':'amd64','url':url,
            'path':path.relative_to(ROOT).as_posix(),'sha256':digest,'bytes':path.stat().st_size,
            'original_payload_sha256_expected':expected,
            'identity_status':'original-frozen-digest-match' if expected else 'supplemental-runtime-input'})
        print(filename, digest, path.stat().st_size, flush=True)
    (ROOT/'metadata/inputs.lock.json').write_text(json.dumps({'schema_version':1,'purpose':'private supplemental examples; no system installation and no formal qualification promotion','inputs':records},indent=2)+'\n')

if __name__=='__main__':
    main()
