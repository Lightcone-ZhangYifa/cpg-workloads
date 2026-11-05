#!/usr/bin/env python3
"""Preparation only: fetch explicitly pinned Ubuntu binary inputs, never install."""
import hashlib
import json
import time
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ITEMS = [('libdwarf-dev', '20210528-1build2', 'universe/d/dwarfutils', 'fae37920d6b4dd6476973090d13e4178b731a1e06d539575310d8b22de2f38f4'), ('libdwarf1', '20210528-1build2', 'universe/d/dwarfutils', '536aa664efdc35a4c5fea851751830cae4cf1dd5bd470ae563be398fc4f734bd')]

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
