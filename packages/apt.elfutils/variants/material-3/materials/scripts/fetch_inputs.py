#!/usr/bin/env python3
"""Preparation only: fetch explicitly pinned Ubuntu binary inputs, never install."""
import hashlib
import json
import time
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ITEMS = [('elfutils', '0.190-1.1ubuntu0.1', 'main/e/elfutils', 'aa0fb4da13d8babb38e3e1fe39b6365016bca9a76d4f8e9f91752fecafee419b'), ('libdw1t64', '0.190-1.1ubuntu0.1', 'main/e/elfutils', 'edaa9ce4221d95f4bd72a9805100902e313092a2f31a7a51e7186be97734714d'), ('libasm1t64', '0.190-1.1ubuntu0.1', 'main/e/elfutils', '81420ff43f36cd447757fee97e70c89c821a907c33a7e5a5a4dd8c76aee3b87a'), ('libdebuginfod1t64', '0.190-1.1ubuntu0.1', 'main/e/elfutils', '7ff18c57198200f4af7e50e0dce29366dc832c10d8c475ca7e0403083e042ea7'), ('libelf1t64', '0.190-1.1ubuntu0.1', 'main/e/elfutils', 'b4aee123a37472d213647594b4f7d4a0d13615b0ca2a6fd33926b768d6b232c2')]

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
