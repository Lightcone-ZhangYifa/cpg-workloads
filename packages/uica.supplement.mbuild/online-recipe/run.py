#!/usr/bin/env python3
"""Offline-exact/online-bounded source recipe for the original uica.supplement.mbuild source."""
import argparse,hashlib,json,os,pathlib,shutil,sys,tempfile,urllib.request
from compiler_playground.packages.archive import pack,verify_package

def validate(file,source):
 p=pathlib.Path(file)
 if p.is_symlink() or not p.is_file() or p.stat().st_size!=source['bytes']:raise ValueError('Original source byte-count lock mismatch')
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1<<20),b''):h.update(block)
 if h.hexdigest()!=source['sha256']:raise ValueError('Original source digest lock mismatch')
 return p

def fetch(source,cache):
 folder=cache/source['sha256'][:2];folder.mkdir(parents=True,exist_ok=True)
 destination=folder/source['sha256']
 if destination.is_file():return validate(destination,source)
 if not source['url'] or not source['url'].startswith('https://'):raise ValueError('Exact original HTTPS source URL required')
 with tempfile.NamedTemporaryFile(prefix='.cpg-locked-source-',dir=folder,delete=False) as temp:
  temporary=pathlib.Path(temp.name)
  try:
   req=urllib.request.Request(source['url'],headers={'User-Agent':'CompilerPlayground-exact-original-source/1.0'})
   with urllib.request.urlopen(req,timeout=30) as stream:
    remaining=source['bytes']
    while True:
     block=stream.read(min(1<<20,remaining+1))
     if not block:break
     if len(block)>remaining:raise ValueError('Source exceeds original byte budget')
     temp.write(block);remaining-=len(block)
   temp.flush();os.fsync(temp.fileno())
  except BaseException:
   temporary.unlink(missing_ok=True)
   raise
 try:
  validate(temporary,source)
  os.replace(temporary,destination)
 except BaseException:
  temporary.unlink(missing_ok=True)
  raise
 return destination

def main():
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','fetch']);ap.add_argument('--recipe',type=pathlib.Path,default=pathlib.Path(__file__).parent);ap.add_argument('--cache',type=pathlib.Path,required=True);ap.add_argument('--output',type=pathlib.Path);ap.add_argument('--no-network',action='store_true');a=ap.parse_args()
 root=a.recipe.resolve();spec=json.loads((root/'package.json').read_text());provenance=json.loads((root/'provenance.json').read_text())
 assert spec['id']=='uica.supplement.mbuild' and len(spec['sources'])==1
 source=spec['sources'][0];saved=a.cache.resolve()/source['sha256'][:2]/source['sha256']
 if saved.is_file():raw=validate(saved,source)
 elif a.no_network:raise ValueError('Original byte-locked source not in offline cache; no network attempted')
 else:raw=fetch(source,a.cache.resolve())
 if a.action=='fetch':print(json.dumps({'status':'verified','path':str(raw),'sha256':source['sha256'],'bytes':source['bytes']}));return
 if a.output is None:raise ValueError('--output is required for prepare')
 packed=pack(spec,a.output,method='source',sources={source['id']:raw},recipe_dir=root/'recipe',provenance=provenance)
 verify_package(a.output,expected_sha256=packed['sha256'],expected_bytes=packed['bytes'])
 print(json.dumps({'status':'prepared','source_original_sha256':source['sha256'],'package_sha256':packed['sha256'],'package_bytes':packed['bytes'],'path':str(a.output)},sort_keys=True))
if __name__=='__main__':main()
