#!/usr/bin/env python3
import argparse, base64, datetime, hashlib, importlib, importlib.metadata, importlib.resources, json, pathlib, sys, zoneinfo
ap=argparse.ArgumentParser()
ap.add_argument('--prefix',required=True)
ap.add_argument('--module',required=True)
ap.add_argument('--dist',required=True)
ap.add_argument('--version',required=True)
a=ap.parse_args(); pref=pathlib.Path(a.prefix).resolve()
assert pathlib.Path(sys.prefix).resolve()==pref,(sys.prefix,pref)
assert importlib.metadata.version(a.dist)==a.version,(a.dist,a.version,importlib.metadata.version(a.dist))
dist=importlib.metadata.distribution(a.dist); hashed=[]
for f in list(dist.files or []):
 if f.hash and f.hash.mode=='sha256':
  full=pathlib.Path(dist.locate_file(f)).resolve()
  assert full.is_relative_to(pref),(full,pref)
  actual=base64.urlsafe_b64encode(hashlib.sha256(full.read_bytes()).digest()).decode().rstrip('=')
  assert actual==f.hash.value,(str(full),actual,f.hash.value)
  hashed.append(str(f))
assert len(hashed)>5,(a.dist,len(hashed))
module=importlib.import_module(a.module)
origin=pathlib.Path(module.__file__).resolve()
assert origin.is_relative_to(pref),(origin,pref)
if a.module=='uri_template':
 from uri_template import expand
 u=expand('https://{host}/users/{id}',host='example.org',id='007'); assert u=='https://example.org/users/007',u
elif a.module=='narwhals':
 import narwhals as nw
 schema=nw.Schema({'x':nw.Int64(),'name':nw.String()});assert list(schema.keys())==['x','name']; assert schema['x']==nw.Int64(),schema
elif a.module=='setuptools':
 import setuptools
 d=setuptools.Distribution({'name':'cpg-offline-fixture','version':'2.1.3'});assert d.get_name()=='cpg-offline-fixture';assert d.get_version()=='2.1.3'
elif a.module=='tzdata':
 t=importlib.resources.files('tzdata').joinpath('zoneinfo/Europe/Berlin')
 with t.open('rb') as f:
  magic=f.read(4);assert magic==b'TZif',magic;f.seek(0);z=zoneinfo.ZoneInfo.from_file(f,key='Europe/Berlin')
 assert datetime.datetime(2026,7,1,tzinfo=z).utcoffset()==datetime.timedelta(hours=2)
 assert datetime.datetime(2026,1,1,tzinfo=z).utcoffset()==datetime.timedelta(hours=1)
elif a.module=='packaging':
 from packaging.specifiers import SpecifierSet
 from packaging.version import Version
 s=SpecifierSet('>=1.8,<2.0');assert Version('1.10')>Version('1.9');assert Version('1.10') in s;assert Version('2.0') not in s
elif a.module=='attrs':
 import attrs
 @attrs.define
 class A:
  name:str
  count:int=attrs.field(converter=int)
 v=A('dataset', '17'); assert attrs.asdict(v)=={'name':'dataset','count':17}
elif a.module=='idna':
 import idna
 encoded=idna.encode('bücher.de');assert encoded==b'xn--bcher-kva.de',encoded
 assert idna.decode(encoded)=='bücher.de'
else:raise AssertionError('Unapproved functional check: '+a.module)
print(json.dumps({'status':'passed','module':a.module,'distribution':a.dist,'version':a.version,'prefix':str(pref),'module_origin':str(origin),'functional_semantic_check':True,'pip_record_hashes_checked':len(hashed)},sort_keys=True))
