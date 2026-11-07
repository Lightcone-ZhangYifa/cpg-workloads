#!/usr/bin/env python3
"""Validate static reference material. Never import or execute upstream code."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def relative_file(root, name):
    rel = PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or rel.as_posix() != name:
        raise ValueError('noncanonical material path')
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing ordinary material file: ' + name)
    if any(p.is_symlink() for p in path.parents if p != root.parent):
        raise ValueError('symlink material parent')
    return path


def validate(root):
    root = Path(root).resolve()
    manifest = json.loads((root/'material-manifest.json').read_text())
    profile = json.loads((root/'PROFILE.json').read_text())
    if profile['policy']['collection'] != 'policy-held' or profile['policy']['upstream_execution'] is not False:
        raise ValueError('material profile would authorize collector execution')
    if profile['qualification']['functional'] is not None:
        raise ValueError('static reference material must not claim profiler functionality')
    declared = set()
    total = 0
    for row in manifest['files']:
        name = row['path']
        if name in declared:
            raise ValueError('duplicate material member')
        declared.add(name)
        path = relative_file(root,name)
        data = path.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('material digest mismatch: ' + name)
        total += len(data)
        if data.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
            raise ValueError('unresolved Git LFS pointer: ' + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
              and p.relative_to(root).as_posix() not in {'material-manifest.json', '.cpg-prefix.json'}}
    if actual != declared:
        raise ValueError('material member set mismatch: ' + repr(sorted(actual ^ declared)))
    for name in profile['required_materials']:
        relative_file(root,name)
    index=json.loads((root/'reference-index.json').read_text())
    for row in index['files']:
        relative_file(root,row['path'])
    if index['file_count'] != len(index['files']) or index['file_count'] == 0:
        raise ValueError('empty or inconsistent reference index')
    for row in json.loads((root/'interface-map.json').read_text())['entries']:
        if 'path' in row:
            relative_file(root,row['path'])
    return {'status':'passed','kind':'availability','resource_id':profile['resource_id'],
            'checked_files':len(declared),'checked_bytes':total,'indexed_files':index['file_count'],
            'upstream_execution':False,'collector_execution':'policy-held',
            'functional_status':'not_run','qualification':'Static material integrity and navigability only.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix')
    args=parser.parse_args()
    print(json.dumps(validate(args.prefix),ensure_ascii=False,sort_keys=True))
