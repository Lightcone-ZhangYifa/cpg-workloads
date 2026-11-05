#!/usr/bin/env python3
"""Exact, version-pinned online acquisition of otelcol release source.

--verification-mirror is for a measured, locally served test only, not a
replacement for the original URL or the immutable release source identity.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile
from urllib.request import urlopen

ORIGINAL_URL = 'https://github.com/open-telemetry/opentelemetry-collector-releases/archive/refs/tags/v0.163.1.tar.gz'
ORIGINAL_SHA = '1fe4777ebd82f19498e41471b06e646708f5ae80c4380e136a4b06cfc15dc884'
ORIGINAL_BYTES = 171270


def fetch(destination, verification_mirror=None):
    url = verification_mirror if verification_mirror is not None else ORIGINAL_URL
    destination=pathlib.Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('refusing to overwrite existing output')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.pinned-otelcol-',dir=str(destination.parent))
    os.close(fd)
    ok=False
    try:
        digest=hashlib.sha256()
        count=0
        with urlopen(url,timeout=30) as response, open(tmp,'wb') as stream:
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                count+=len(chunk)
                if count>ORIGINAL_BYTES:
                    raise ValueError('network payload exceeds exact catalog size')
                digest.update(chunk);stream.write(chunk)
            stream.flush();os.fsync(stream.fileno())
        if count!=ORIGINAL_BYTES or digest.hexdigest()!=ORIGINAL_SHA:
            raise ValueError('download size/SHA256 does not match original catalog lock')
        os.link(tmp,destination)
        ok=True
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)
    return {'status':'passed','url':ORIGINAL_URL,'bytes':ORIGINAL_BYTES,'sha256':ORIGINAL_SHA,
            'transfer_mode':'local_http_verification_mirror' if verification_mirror else 'original_upstream_url',
            'saved':str(destination)}

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    p.add_argument('--verification-mirror')
    args=p.parse_args()
    try: print(json.dumps(fetch(args.output,args.verification_mirror),sort_keys=True))
    except Exception as e:
        print(json.dumps({'status':'failed','reason':str(e)}),file=sys.stderr);sys.exit(1)
