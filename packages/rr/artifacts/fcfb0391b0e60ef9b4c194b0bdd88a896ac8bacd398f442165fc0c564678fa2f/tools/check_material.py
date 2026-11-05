#!/usr/bin/env python3
"""Static verification only of the exact rr 5.10.0 upstream release DEB.

This does NOT certify rr record/replay, ptrace, performance counters or OCI.
"""
from __future__ import annotations
import argparse,hashlib,json,pathlib,subprocess,sys
SHA='fe3ccb579eab96220b2b91b918ce80da7173f3c098804370a93247a056fab3a1'
BYTES=2974106

def inspect(path):
    p=pathlib.Path(path)
    if p.is_symlink() or not p.is_file():raise ValueError('not a regular original release file')
    if p.stat().st_size!=BYTES or hashlib.sha256(p.read_bytes()).hexdigest()!=SHA:
        raise ValueError('original DEB size or SHA mismatch')
    report={}
    for key in ('Package','Version','Architecture'):
        run=subprocess.run(['dpkg-deb','--field',str(p),key],capture_output=True,text=True,timeout=10)
        if run.returncode:raise ValueError(f'Unable to inspect upstream DEB control field {key}')
        report[key]=run.stdout.strip()
    assert report=={'Package':'rr','Version':'5.10.0','Architecture':'amd64'}, report
    listing=subprocess.run(['dpkg-deb','--contents',str(p)],capture_output=True,text=True,timeout=20)
    if listing.returncode!=0:raise ValueError('Unpacking listing failed')
    for name in ('./usr/bin/rr','./usr/lib/rr/librrpreload.so','./usr/share/rr/64bit-core.xml'):
        if name not in listing.stdout: raise ValueError('missing upstream release member: '+name)
    return {'status':'passed','source_sha256':SHA,'bytes':BYTES,'deb_control':report,
        'original_member_requirements_passed':True,'scope':'static-original-release-material-only'}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);args=p.parse_args()
 try: print(json.dumps(inspect(pathlib.Path(args.prefix)/'payloads/rr'),sort_keys=True))
 except Exception as error: print(json.dumps({'status':'failed','reason':str(error)}),file=sys.stderr);sys.exit(1)
