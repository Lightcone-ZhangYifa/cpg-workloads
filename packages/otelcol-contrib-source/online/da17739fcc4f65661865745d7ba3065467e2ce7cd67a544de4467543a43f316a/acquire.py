#!/usr/bin/env python3
"""Online acquisition with exact immutable upstream tag and byte lock."""
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,sys,tempfile
from urllib.request import urlopen
URL='https://github.com/open-telemetry/opentelemetry-collector-contrib/archive/refs/tags/v0.163.0.tar.gz'
SHA='a9277bf9d19f9359a4a6f262e9c6cd98524bd6f2442950a8dce615fbe062f98e'
BYTES=16944016

def fetch(output,verification_mirror=None):
 output=pathlib.Path(output).absolute()
 if output.exists() or output.is_symlink():raise FileExistsError('output already exists')
 output.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.otelcol-contrib-exact-',dir=str(output.parent));os.close(fd)
 try:
  digest=hashlib.sha256();size=0
  with urlopen(verification_mirror or URL,timeout=30) as response,open(tmp,'wb') as target:
   while True:
    part=response.read(1024*1024)
    if not part:break
    size+=len(part)
    if size>BYTES:raise ValueError('oversize transfer is not original resource')
    digest.update(part);target.write(part)
   target.flush();os.fsync(target.fileno())
  if size!=BYTES or digest.hexdigest()!=SHA:raise ValueError('transfer SHA/size mismatch')
  os.link(tmp,output)
 finally:pathlib.Path(tmp).unlink(missing_ok=True)
 return {'status':'passed','original_url':URL,'bytes':size,'sha256':SHA,
         'test_mirror_used':verification_mirror is not None}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--verification-mirror');a=p.parse_args()
 try:print(json.dumps(fetch(a.output,a.verification_mirror),sort_keys=True))
 except Exception as error:print(json.dumps({'status':'failed','reason':str(error)}),file=sys.stderr);sys.exit(1)
