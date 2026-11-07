#!/usr/bin/env python3
import argparse,hashlib,json,tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
lock=json.loads((a.prefix/'sdk-lock.json').read_text());archive=a.prefix/lock['path'];h=hashlib.sha512()
with archive.open('rb') as f:
 for block in iter(lambda:f.read(1048576),b''):h.update(block)
if archive.stat().st_size!=lock['bytes'] or h.hexdigest()!=lock['sha512']:raise ValueError('SDK digest mismatch')
data=json.loads((a.prefix/'official-releases.json').read_text());matches=[]
def visit(v):
 if isinstance(v,dict):
  if v.get('url')==lock['url'] and v.get('hash','').lower()==lock['sha512']:matches.append(v)
  for x in v.values():visit(x)
 elif isinstance(v,list):
  for x in v:visit(x)
visit(data)
if not matches:raise ValueError('SDK not bound to official release index')
required={'dotnet','sdk/8.0.427/Roslyn/bincore/csc.dll','packs/Microsoft.NETCore.App.Ref/8.0.33/ref/net8.0/System.Runtime.dll','shared/Microsoft.NETCore.App/8.0.33/System.Private.CoreLib.dll'}
seen=set()
with tarfile.open(archive,'r:gz') as t:
 for m in t:
  if m.name.removeprefix('./') in required:seen.add(m.name.removeprefix('./'))
if seen!=required:raise ValueError('Offline SDK compiler/reference/runtime closure incomplete')
result={'status':'passed','checks':['official SHA512 and byte count','official release index binding','Roslyn/reference/runtime archive members'],'version':lock['version'],'runtime':lock['runtime'],'archive_sha512':h.hexdigest(),'matched_release_entries':len(matches),'required_members':sorted(seen),'evidence_files':[],'qualification':'support material only; no new upstream resource or source-build qualification'}
(a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('CPG_CHECK_PASS support.dotnet-sdk-8')
