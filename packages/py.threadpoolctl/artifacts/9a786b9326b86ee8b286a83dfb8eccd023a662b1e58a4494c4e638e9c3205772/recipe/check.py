#!/usr/bin/env python3
import argparse,importlib,importlib.metadata as meta,json,pathlib,sys,tempfile
ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--module',required=True);ap.add_argument('--dist',required=True);ap.add_argument('--version',required=True);a=ap.parse_args()
prefix=pathlib.Path(a.prefix).resolve();assert pathlib.Path(sys.prefix).resolve()==prefix,(sys.prefix,prefix)
assert meta.version(a.dist)==a.version
m=importlib.import_module(a.module);origin=pathlib.Path(m.__file__).resolve();assert origin.is_relative_to(prefix),(origin,prefix)
if a.module=='iniconfig':
 with tempfile.TemporaryDirectory() as td:
  p=pathlib.Path(td)/'data.ini';p.write_text('[section]\nkey = yes\n')
  config=m.IniConfig(str(p));assert config.sections['section']['key']=='yes'
elif a.module=='pluggy':
 hookspec=m.HookspecMarker('cpg');hookimpl=m.HookimplMarker('cpg')
 class Spec:
  @hookspec
  def score(self, n):pass
 class Plugin:
  @hookimpl
  def score(self, n):return n+1
 pm=m.PluginManager('cpg');pm.add_hookspecs(Spec);pm.register(Plugin());assert pm.hook.score(n=5)==[6]
elif a.module=='threadpoolctl':
 result=m.threadpool_info();assert isinstance(result,list)
 with m.threadpool_limits(limits=1):assert isinstance(m.threadpool_info(),list)
else:raise AssertionError('module smoke unapproved')
print(json.dumps({'status':'passed','module':a.module,'version':a.version,'isolated_prefix':str(prefix),'origin':str(origin),'functional_smoke':True},sort_keys=True))
