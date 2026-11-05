#!/usr/bin/env python3
"""Check a complete immutable material tree, without executing its contents."""
from __future__ import annotations
import argparse,hashlib,json,os,stat
from pathlib import Path

def inventory(root):
    rows=[]
    for base,dirs,files in os.walk(root,followlinks=False):
        for n in sorted(dirs+files):
            p=Path(base)/n;r={'path':p.relative_to(root).as_posix(),'mode':stat.S_IMODE(p.lstat().st_mode)}
            if p.is_symlink():r.update(kind='symlink',target=os.readlink(p))
            elif p.is_dir():r['kind']='directory'
            elif p.is_file():
                with p.open('rb') as f:d=hashlib.file_digest(f,'sha256').hexdigest()
                r.update(kind='file',bytes=p.stat().st_size,sha256=d)
            else:raise ValueError('Special object not admitted: '+str(p))
            if r['path'] != '.cpg-prefix.json':rows.append(r)
    return sorted(rows,key=lambda r:r['path'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);a=p.parse_args()
    expected=json.loads(a.manifest.read_text())['files'];actual=inventory(a.prefix)
    if actual!=expected:
        print(json.dumps({'status':'failed','reason':'Complete file identity, mode, link or membership differs'}));return 1
    print(json.dumps({'status':'passed','entries':len(actual),'files':sum(r['kind']=='file' for r in actual)}));return 0
if __name__=='__main__':raise SystemExit(main())
