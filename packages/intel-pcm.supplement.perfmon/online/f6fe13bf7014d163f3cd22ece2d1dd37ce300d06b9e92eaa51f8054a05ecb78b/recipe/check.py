#!/usr/bin/env python3
"""Verify all exact upstream material members without running PCM or PMU code."""
from __future__ import annotations
import argparse, hashlib, json, os, stat
from pathlib import Path

def snapshot(root: Path):
    rows = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if relative == '.cpg-prefix.json':
            continue
        info = path.lstat()
        row = {'path':relative, 'mode':stat.S_IMODE(info.st_mode)}
        if stat.S_ISDIR(info.st_mode): row['kind']='directory'
        elif stat.S_ISLNK(info.st_mode): row.update(kind='symlink',target=os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            row.update(kind='file',bytes=info.st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        else: raise ValueError('Unsupported installed member: '+relative)
        rows.append(row)
    return rows

def main():
    a=argparse.ArgumentParser();a.add_argument('--prefix',type=Path,required=True);a.add_argument('--manifest',type=Path,required=True)
    x=a.parse_args(); expected=json.loads(x.manifest.read_text()); actual=snapshot(x.prefix)
    before={r['path']:r for r in expected['files']};after={r['path']:r for r in actual}
    if len(before)!=len(expected['files']) or len(after)!=len(actual):
        raise ValueError('Duplicate path in material inventory')
    if before!=after:
        changed=[n for n in sorted(before.keys()|after.keys()) if before.get(n)!=after.get(n)]
        raise ValueError('Material inventory mismatch: '+', '.join(changed[:15]))
    print(json.dumps({'status':'passed','resource_id':expected['resource_id'],'scope':expected['scope'],'file_count':sum(r['kind']=='file' for r in actual),'directory_count':sum(r['kind']=='directory' for r in actual),'source_archive_sha256':expected['original_source']['sha256'],'pmu_executed':False,'oci_executed':False},sort_keys=True))
if __name__=='__main__': main()
