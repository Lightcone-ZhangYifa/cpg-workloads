#!/usr/bin/env python3
import argparse, json, os, pathlib, shutil, subprocess, sys, tempfile
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--recipe',required=True);a=p.parse_args()
prefix=pathlib.Path(a.prefix).resolve();recipe=pathlib.Path(a.recipe).resolve()
env=dict(os.environ);env['PYTHONPATH']=str(prefix);env['PYTHONDONTWRITEBYTECODE']='1'
code="import json, pathlib, mbuild; p=pathlib.Path(mbuild.__file__).resolve(); root=pathlib.Path(" + repr(str(prefix)) + ").resolve(); assert p.is_relative_to(root), (p,root); print(json.dumps({'mbuild_path':str(p),'plan_t':hasattr(mbuild,'plan_t'),'dag_t':hasattr(mbuild,'dag_t')}))"
i=subprocess.run([sys.executable,'-B','-c',code],cwd='/',env=env,text=True,capture_output=True,timeout=20)
assert i.returncode==0,(i.stdout,i.stderr)
assert json.loads(i.stdout)['plan_t'] and json.loads(i.stdout)['dag_t']
with tempfile.TemporaryDirectory(prefix='cpg-mbuild-native-probe-') as t:
  root=pathlib.Path(t);fixture=recipe/'fixture'
  for f in fixture.iterdir():
    if f.is_file():shutil.copy2(f,root/f.name)
  (root/'find.py').write_text('# Use independent prefix PYTHONPATH; original upstream repository-specific find.py preserved in original archive\n')
  cmd=[sys.executable,'-B','mfile.py','--jobs','2']
  r=subprocess.run(cmd,cwd=root,env=env,capture_output=True,text=True,timeout=90)
  assert r.returncode==0,(r.stdout,r.stderr)
  candidates=[x for x in root.rglob('main') if x.is_file() and os.access(x,os.X_OK)]
  assert candidates, ('No compiled executable produced by mbuild',r.stdout,r.stderr)
  e=subprocess.run([str(candidates[0])],cwd=root,text=True,capture_output=True,timeout=10)
  assert e.returncode==0,(e.stdout,e.stderr)
  print(json.dumps({'status':'passed','import':json.loads(i.stdout),'fixture':'tests/circular-dep','command':cmd,'compiled_executable':str(candidates[0].relative_to(root)), 'compiler': 'mbuild original C compile_and_link', 'exit_code':e.returncode},sort_keys=True))
