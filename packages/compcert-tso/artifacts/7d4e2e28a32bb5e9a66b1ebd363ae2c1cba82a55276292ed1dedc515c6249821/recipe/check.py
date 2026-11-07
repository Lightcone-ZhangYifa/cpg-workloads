#!/usr/bin/env python3
"""Verify installed research material and all indexed declaration locations."""

if not __debug__:
    raise RuntimeError("CPG worker095 integrity checks require unoptimized Python")
from pathlib import Path
import hashlib
import json
import re
import sys

prefix=Path(sys.argv[1]).resolve()
manifest=json.loads((prefix/'material-manifest.json').read_text())
for row in manifest['files']:
    path=prefix/row['path']
    if not path.is_file() or path.is_symlink():raise AssertionError(row['path'])
    b=path.read_bytes()
    if len(b)!=row['bytes'] or hashlib.sha256(b).hexdigest()!=row['sha256']:raise AssertionError('material bytes differ: '+row['path'])
index=json.loads((prefix/'index'/'selected.json').read_text())
for item in index['entries']:
    f=prefix/'source'/item['path'];b=f.read_bytes()
    assert hashlib.sha256(b).hexdigest()==item['source_sha256'],item
    lines=b.decode('utf-8',errors='replace').splitlines()
    assert 1<=item['line']<=len(lines),item
    assert re.search(r'\b'+re.escape(item['symbol'])+r'\b',lines[item['line']-1]),item
leaves=json.loads((prefix/'index'/'leaves.json').read_text())['leaves']
for item in leaves:
    assert any(x['path']==item['path'] and x['line']==item['line'] and x['symbol']==item['symbol'] for x in index['entries']),item
print(json.dumps({'status':'passed','kind':'availability','resource_id':manifest['resource_id'],'verified_files':len(manifest['files']),'selected_symbols':len(index['entries']),'leaf_mappings':len(leaves),'functional_status':'not_run','proof_replay':'not_run'},sort_keys=True))
