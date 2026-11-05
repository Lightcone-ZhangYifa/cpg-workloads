#!/usr/bin/env python3
"""Check exact original source materials, not built Collector functionality."""
from __future__ import annotations
import argparse,hashlib,json,pathlib,tarfile,sys
SHA='a9277bf9d19f9359a4a6f262e9c6cd98524bd6f2442950a8dce615fbe062f98e'
BYTES=16944016
ROOT='opentelemetry-collector-contrib-0.163.0'
MEMBER_COUNT=16969
FILE_COUNT=13916
LOGICAL_BYTES=90310786
REQUIRED=('README.md','LICENSE','go.mod','cmd/telemetrygen/go.mod','config/configdbauth/go.mod')

def inspect(path):
 path=pathlib.Path(path)
 if not path.is_file() or path.is_symlink():raise ValueError('missing or linked original archive')
 if path.stat().st_size!=BYTES or hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise ValueError('original archive SHA/bytes mismatch')
 with tarfile.open(path,'r:gz') as tar:
  members=tar.getmembers();names=set();regular=0;logical=0
  if len(members)!=MEMBER_COUNT:raise ValueError('original source entry count mismatch')
  for member in members:
   pure=pathlib.PurePosixPath(member.name)
   if pure.is_absolute() or '..' in pure.parts or not member.name.startswith(ROOT+'/') and member.name!=ROOT:
    raise ValueError('escape or unexpected source root: '+member.name)
   if not (member.isfile() or member.isdir()):raise ValueError('unexpected link/device: '+member.name)
   if member.name in names:raise ValueError('duplicate member: '+member.name)
   names.add(member.name)
   if member.isfile():regular+=1;logical+=member.size
  if regular!=FILE_COUNT or logical!=LOGICAL_BYTES:raise ValueError('original source closure missing data')
  if any(ROOT+'/'+r not in names for r in REQUIRED):raise ValueError('missing expected source evidence')
  if ROOT+'/.gitmodules' in names:raise ValueError('submodule closure not independently resolved')
 return {'status':'passed','sha256':SHA,'archive_bytes':BYTES,'original_members':MEMBER_COUNT,
         'ordinary_files':FILE_COUNT,'source_logical_bytes':LOGICAL_BYTES,
         'scope':'exact_original_static_source_material_only','native_build_qualified':False}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);a=p.parse_args()
 try:print(json.dumps(inspect(pathlib.Path(a.prefix)/'sources/otelcol-contrib-0.163.0.tar.gz'),sort_keys=True))
 except Exception as error:print(json.dumps({'status':'failed','reason':str(error)}),file=sys.stderr);sys.exit(1)
