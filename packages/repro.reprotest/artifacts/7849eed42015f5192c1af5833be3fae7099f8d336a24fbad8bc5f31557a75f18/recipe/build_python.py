#!/usr/bin/env python3
"""Build upstream Python sdists using only the exact bundled offline wheels."""
from pathlib import Path
import argparse, os, json, shutil, subprocess, sys, tarfile, zipfile, hashlib
ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--build',type=Path,required=True);ap.add_argument('--prefix',type=Path,required=True)
a=ap.parse_args();src=a.source.resolve();build=a.build.resolve();prefix=a.prefix.resolve();meta=json.loads((src/'bundle.json').read_text())
for row in meta['files']:
    p=src/row['path']
    assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==row['sha256'],row['path']
bootstrap=build/'build-tools';bootstrap.mkdir(exist_ok=True)
for p in (src/'bootstrap').glob('*.whl'):
    with zipfile.ZipFile(p) as z:z.extractall(bootstrap)
env=dict(os.environ,PYTHONPATH=str(bootstrap),PYTHONDONTWRITEBYTECODE='1',SOURCE_DATE_EPOCH='946684800',PIP_NO_INDEX='1')
runtime=prefix/'runtime/python';runtime.mkdir(parents=True,exist_ok=True)
for p in (src/'dependencies').glob('*.whl'):
    with zipfile.ZipFile(p) as z:z.extractall(runtime)
receipts=[]
for row in meta['upstream']:
    sd=build/'source'/row['name'];sd.mkdir(parents=True,exist_ok=True)
    with tarfile.open(src/row['sdist']) as t:t.extractall(sd,filter='data')
    project=next(p for p in sd.iterdir() if p.is_dir());dist=build/'built-wheels';dist.mkdir(exist_ok=True)
    cmd=[sys.executable,'setup.py','bdist_wheel','--dist-dir',str(dist)]
    p=subprocess.run(cmd,cwd=project,env=env,capture_output=True,text=True)
    (build/(row['name']+'-build.stdout')).write_text(p.stdout);(build/(row['name']+'-build.stderr')).write_text(p.stderr)
    assert p.returncode==0,(row['name'],p.returncode,p.stderr)
    wh=next(p for p in dist.glob('*.whl') if p.name.startswith(row['name'].replace('-','_')+'-'))
    with zipfile.ZipFile(wh) as z:z.extractall(runtime)
    receipts.append({'name':row['name'],'sdist_sha256':hashlib.file_digest((src/row['sdist']).open('rb'),'sha256').hexdigest(),'wheel_sha256':hashlib.file_digest(wh.open('rb'),'sha256').hexdigest(),'command':cmd,'network':'local setuptools/wheel/dependencies only'})
shutil.copytree(src/'scaffold',prefix,dirs_exist_ok=True)
(prefix/'SOURCE-BUILD-RECEIPT.json').write_text(json.dumps(receipts,indent=2))
print(json.dumps({'status':'built-from-upstream-sdists','packages':[x['name'] for x in receipts]}))
