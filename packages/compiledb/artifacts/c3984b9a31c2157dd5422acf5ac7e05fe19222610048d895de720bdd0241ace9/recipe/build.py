#!/usr/bin/env python3
"""Install the frozen wheel closure without network access or global installs."""
import argparse,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--prefix',type=Path,required=True);p.add_argument('--build',type=Path,required=True);a=p.parse_args()
recipe=Path(__file__).resolve().parent;config=json.loads((recipe/'python-config.json').read_text())
if sys.version_info[:2]!=(3,12):raise SystemExit('The frozen wheel closure requires Python 3.12; rebuild a distinct closure for another Python ABI.')
wheelhouse=a.build/'offline-wheels';wheelhouse.mkdir(parents=True,exist_ok=True)
for entry in config['wheels']:
 source=a.source if entry['primary'] else recipe/'inputs'/entry['file']
 with source.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 if digest!=entry['sha256'] or source.stat().st_size!=entry['bytes']:raise ValueError('Wheel input differs: '+entry['file'])
 shutil.copy2(source,wheelhouse/entry['file'])
target=a.prefix/'lib/python';target.mkdir(parents=True,exist_ok=True)
command=[sys.executable,'-m','pip','--disable-pip-version-check','--no-cache-dir','install','--no-index','--no-compile','--find-links',str(wheelhouse),'--require-hashes','--target',str(target),'-r',str(recipe/'requirements.lock')]
print(json.dumps({'argv':command}),flush=True)
env=os.environ.copy();env.update(PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_CONFIG_FILE='/dev/null',PYTHONNOUSERSITE='1')
subprocess.run(command,check=True,env=env)
if (target/'bin').exists():shutil.rmtree(target/'bin')
(a.prefix/'bin').mkdir(exist_ok=True)
for name in config['entrypoints']:
 source=recipe/'entrypoints'/name;shutil.copy2(source,a.prefix/'bin'/name)
share=a.prefix/'share'/config['id'];share.mkdir(parents=True,exist_ok=True)
shutil.copytree(wheelhouse,share/'wheelhouse')
shutil.copy2(recipe/'requirements.lock',share/'requirements.lock')
shutil.copy2(recipe/'python-config.json',share/'input-lock.json')
