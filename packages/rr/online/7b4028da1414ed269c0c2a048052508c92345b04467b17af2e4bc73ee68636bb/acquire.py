#!/usr/bin/env python3
"""Acquire the original exact upstream rr DEB; test mirrors never replace pin."""
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,sys,tempfile
from urllib.request import urlopen
URL='https://github.com/rr-debugger/rr/releases/download/5.10.0/rr-5.10.0-Linux-x86_64.deb'
SHA='fe3ccb579eab96220b2b91b918ce80da7173f3c098804370a93247a056fab3a1'
BYTES=2974106

def fetch(output,verification_mirror=None):
 output=pathlib.Path(output).absolute()
 if output.exists() or output.is_symlink(): raise FileExistsError('refuse existing output')
 output.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.rr-locked-',dir=str(output.parent));os.close(fd)
 try:
  total=0;digest=hashlib.sha256()
  with urlopen(verification_mirror or URL,timeout=30) as response,open(tmp,'wb') as target:
   while True:
    data=response.read(1024*1024)
    if not data:break
    total+=len(data)
    if total>BYTES:raise ValueError('transferred more bytes than exact original lock')
    target.write(data);digest.update(data)
   target.flush();os.fsync(target.fileno())
  if total!=BYTES or digest.hexdigest()!=SHA:raise ValueError('transfer differs from exact original lock')
  os.link(tmp,output)
 finally: pathlib.Path(tmp).unlink(missing_ok=True)
 return {'status':'passed','original_url':URL,'bytes':BYTES,'sha256':SHA,
         'transfer_mode':'verification_mirror' if verification_mirror else 'upstream_url'}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--verification-mirror');args=parser.parse_args()
 try:print(json.dumps(fetch(args.output,args.verification_mirror),sort_keys=True))
 except Exception as error:print(json.dumps({'status':'failed','reason':str(error)}),file=sys.stderr);sys.exit(1)
