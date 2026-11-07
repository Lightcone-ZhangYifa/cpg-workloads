#!/usr/bin/env python3
"""CPG source hook: use only manager-verified local archives, build, copy prefix."""
import argparse,json,pathlib,shutil,subprocess,sys

p=argparse.ArgumentParser()
for k in ['recipe','assets','build','prefix']:p.add_argument('--'+k,required=True,type=pathlib.Path)
p.add_argument('--name',required=True)
a=p.parse_args()
runner=a.build/'offline-runner';runner.mkdir()
for name in ['replay_lightweight.py','runtime_layout.py','inputs.lock.json']:
    shutil.copy2(a.recipe/name,runner/name)
shutil.copytree(a.recipe/'fixtures',runner/'fixtures')
raw=runner/'raw';raw.mkdir()
needed={a.name}
if a.name=='asmjit':needed.add('cmake')
if a.name=='luajit':needed.add('libluajit-frozen-dev')
lock=json.loads((runner/'inputs.lock.json').read_text())
for entry in lock['inputs']:
    if entry['name'] in needed:
        source=a.assets/entry['path'];dest=runner/entry['path']
        if not source.is_file() or source.is_symlink():raise RuntimeError('Missing verified ordinary input '+str(source))
        shutil.copy2(source,dest)
out=a.build/'actual-build'
subprocess.run([sys.executable,'-B',str(runner/'replay_lightweight.py'),'--output',str(out),'--only',a.name],check=True)
report=json.loads((out/'replay-report.json').read_text())
if not report['all_passed']:raise RuntimeError('Source build functional checks did not pass')
prefix=out/'install'/a.name
shutil.copytree(prefix,a.prefix,dirs_exist_ok=True,symlinks=False)
print(json.dumps({'status':'passed','method':'source','network_used':False,'resource':a.name,'build_report':str(out/'replay-report.json'),'prefix':str(a.prefix)}))
