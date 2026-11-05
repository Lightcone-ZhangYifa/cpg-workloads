#!/usr/bin/env python3
"""Acquire a SINGLE exact-lock upstream tar material; never use HEAD/latest.

Default uses original HTTPS GET, exact locked bytes/SHA, bounded reads, and an
allowlisted complete member manifest. For local recipe tests, only loopback HTTP
is permitted with BOTH --test-url and --allow-loopback-test; that mode never
claims remote upstream acquisition. Installs into a NEW independent directory.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import tarfile
import tempfile
from urllib.parse import urlparse
from urllib.request import Request,urlopen


def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as fp:
  for x in iter(lambda:fp.read(1024*1024),b''):h.update(x)
 return h.hexdigest()


def require_manifest(path):
 m=json.loads(Path(path).read_text())
 if m.get('kind')!='complete_pinned_tar_source_material':raise ValueError('Wrong tar material manifest schema')
 source=m['original_source_lock']
 if source['id']!=m['resource_id'] or not urlparse(source['url']).scheme=='https':
  raise ValueError('Invalid exact source provenance')
 if not len(source['sha256'])==64 or source['bytes']<=0 or source['extract'] is not True or source['strip_root'] is not True:
  raise ValueError('Incomplete exact source lock')
 if not m['member_inventory'] or not m['archive_root'] or not m['original_definition_sha256']:
  raise ValueError('Missing member or original definition evidence')
 if len(m['member_inventory'])!=m['archive_total_members']-1:
  raise ValueError('Full original archive member count is inconsistent')
 return m,source


def expand_and_check(source_tar,source_root,manifest):
 expected={x['path']:x for x in manifest['member_inventory']}
 if len(expected)!=len(manifest['member_inventory']):raise ValueError('Duplicate original member paths in lock')
 seen=set()
 with tarfile.open(source_tar,'r:gz') as tar:
  rows=tar.getmembers()
  if len(rows)!=manifest['archive_total_members']:raise ValueError('Original archive changed member count')
  for m in rows:
   if m.type not in (tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.DIRTYPE):
    raise ValueError('Original archive contains unsupported special member: '+m.name)
   orig=PurePosixPath(m.name)
   if orig.is_absolute() or '..' in orig.parts or orig.parts[0]!=manifest['archive_root']:
    raise ValueError('Archive path escapes original root')
   if len(orig.parts)==1:
    if not m.isdir():raise ValueError('Archive root not directory')
    continue
   rel=PurePosixPath(*orig.parts[1:]).as_posix()
   if rel not in expected or rel in seen:raise ValueError('Unknown or duplicate material member: '+rel)
   seen.add(rel)
   row=expected[rel]
   if row['type']!=('file' if m.isfile() else 'directory') or row['mode']!=(m.mode&0o777):
    raise ValueError('Member mode/kind mismatch: '+rel)
   target=source_root/rel
   if m.isdir():target.mkdir(parents=True,exist_ok=True)
   else:
    if m.size!=row['bytes'] or m.size>20_000_000:raise ValueError('Member size mismatch: '+rel)
    buf=tar.extractfile(m).read()
    if len(buf)!=m.size or hashlib.sha256(buf).hexdigest()!=row['sha256']:
     raise ValueError('Member SHA256 mismatch: '+rel)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as fp:fp.write(buf)
   target.chmod(row['mode'])
 if seen != set(expected):raise ValueError('Missing original archive members')
 actual={p.relative_to(source_root).as_posix():p for p in source_root.rglob('*')}
 if set(actual)!=set(expected):raise ValueError('Installed material file set differs')
 for name,p in actual.items():
  if p.is_symlink() or (p.stat().st_mode&0o777)!=expected[name]['mode']:
   raise ValueError('Unsupported link or mode mismatch')
 return {'members':len(rows),'regular_files':sum(x['type']=='file' for x in expected.values()),
         'directories':sum(x['type']=='directory' for x in expected.values())}


def acquire(manifest_path,output,test_url=None,allow_loopback_test=False):
 m,lock=require_manifest(manifest_path)
 target=Path(output).absolute()
 if target.exists() or target.is_symlink():raise FileExistsError(target)
 target.parent.mkdir(parents=True,exist_ok=True)
 url=lock['url'];testing=test_url is not None
 if testing:
  test=urlparse(test_url)
  if not allow_loopback_test or test.scheme!='http' or test.hostname not in {'127.0.0.1','localhost','::1'}:
   raise ValueError('Test URL must be explicitly authorized and local-only')
  url=test_url
 req=Request(url,headers={'User-Agent':'compiler-playground-exact-tar-material/1.0'})
 with tempfile.TemporaryDirectory(prefix='.cpg-tar-acquire-',dir=target.parent) as tmp:
  ready=Path(tmp)/'ready';ready.mkdir()
  source_tar=ready/m['original_archive_name']
  count=0;hasher=hashlib.sha256()
  with urlopen(req,timeout=25) as stream, source_tar.open('xb') as dest:
   final=stream.geturl();p=urlparse(final)
   if testing:
    if p.scheme!='http' or p.hostname not in {'127.0.0.1','localhost','::1'}:
     raise ValueError('Test request redirected outside loopback')
   elif p.scheme!='https':raise ValueError('Canonical original source transfer must remain HTTPS')
   length=stream.headers.get('Content-Length')
   if length is not None and int(length)!=lock['bytes']:
    raise ValueError('Content-Length differs from the pinned size')
   while True:
    chunk=stream.read(min(64*1024,lock['bytes']+1-count))
    if not chunk:break
    count+=len(chunk)
    if count>lock['bytes']:raise ValueError('GET exceeded byte cap')
    hasher.update(chunk);dest.write(chunk)
  if count!=lock['bytes'] or hasher.hexdigest()!=lock['sha256']:
   raise ValueError('GET does not match pinned original bytes and SHA256')
  unpack=ready/lock['material_path'];unpack.mkdir(parents=True)
  content=expand_and_check(source_tar,unpack,m)
  receipt={'resource_id':m['resource_id'],'original_url':lock['url'],'actual_get_url':final,
    'sha256':lock['sha256'],'bytes':count,'verified_original_complete_tar':True,
    'unpacked_original_members':content,'loopback_test_only':testing,
    'official_upstream_GET_executed':not testing,
    'native_functionality_qualified':False,'target_execution_qualified':False}
  (ready/'acquisition-receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
  os.replace(ready,target)
 return receipt


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--manifest',type=Path,default=Path(__file__).with_name('material-manifest.json'))
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--test-url')
 p.add_argument('--allow-loopback-test',action='store_true')
 a=p.parse_args();print(json.dumps(acquire(a.manifest,a.output,a.test_url,a.allow_loopback_test),indent=2))

if __name__=='__main__':main()
