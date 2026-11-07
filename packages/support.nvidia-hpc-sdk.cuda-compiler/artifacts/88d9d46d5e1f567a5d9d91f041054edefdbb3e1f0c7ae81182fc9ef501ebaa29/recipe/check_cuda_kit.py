#!/usr/bin/env python3
"""Check the support kit's own files; this does not certify a vendor SDK."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--prefix',type=Path,required=True)
a=p.parse_args();root=a.prefix.resolve()
expected=json.loads((root/'kit-inventory.json').read_text())
actual=[]
for f in sorted(root.rglob('*')):
    rel=f.relative_to(root).as_posix()
    if rel in {'kit-inventory.json','.cpg-prefix.json'} or f.is_dir():continue
    if f.is_symlink() or not f.is_file():raise RuntimeError('nonregular support-kit file')
    actual.append({'path':rel,'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
if actual!=expected:raise RuntimeError('support-kit files differ from frozen inventory')
for f in root.glob('*.py'):
    compile(f.read_text(),str(f),'exec')
lock=json.loads((root/'cuda-local-sdk-lock.json').read_text())
report=json.loads((root/'evidence/final-report.json').read_text())
print(json.dumps({'status':'passed','kind':'availability','files_verified':len(actual),
                  'scope':'own support kit availability only; vendor SDK and GPU execution not certified'}))
