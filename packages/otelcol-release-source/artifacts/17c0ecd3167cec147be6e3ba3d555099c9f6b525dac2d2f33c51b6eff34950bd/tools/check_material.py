#!/usr/bin/env python3
"""Verify the exact originally recorded otelcol release source archive.

This does not claim an OpenTelemetry Collector build, runtime, OCI or telemetry
pipeline validation; only static source material availability.
"""
import argparse
import hashlib
import json
import pathlib
import tarfile
import sys

LOCK_SHA = '1fe4777ebd82f19498e41471b06e646708f5ae80c4380e136a4b06cfc15dc884'
LOCK_BYTES = 171270
ROOT = 'opentelemetry-collector-releases-0.163.1'
MEMBER_COUNT = 207
REQUIRED = ('LICENSE', 'go.mod', 'README.md', 'distributions/otelcol/README.md',
            'distributions/otelcol-contrib/README.md')


def inspect(path):
    path = pathlib.Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('original material must be a regular file')
    if path.stat().st_size != LOCK_BYTES:
        raise ValueError('original bytes differ from catalog lock')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != LOCK_SHA:
        raise ValueError('original SHA256 differs from catalog lock')
    with tarfile.open(path, mode='r:gz') as archive:
        entries = archive.getmembers()
        if len(entries) != MEMBER_COUNT:
            raise ValueError('archive member count differs from original inspected closure')
        names = set()
        for entry in entries:
            p = pathlib.PurePosixPath(entry.name)
            if p.is_absolute() or '..' in p.parts or not entry.name.startswith(ROOT):
                raise ValueError('archive member path escape or changed root: ' + entry.name)
            if not entry.isfile() and not entry.isdir():
                raise ValueError('unreviewed link/device member: ' + entry.name)
            if entry.name in names:
                raise ValueError('duplicate archive member: ' + entry.name)
            names.add(entry.name)
        missing = {ROOT+'/'+name for name in REQUIRED} - names
        if missing:
            raise ValueError('source distribution missing required members: ' + str(sorted(missing)))
        if ROOT+'/.gitmodules' in names:
            raise ValueError('submodule closure requires separate exact resolution')
    return {'status':'passed','original_sha256':sha,'original_bytes':LOCK_BYTES,
            'source_members':len(entries),'root':ROOT,'scope':'static-original-source-material-only'}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--prefix',required=True)
    args=p.parse_args()
    source=pathlib.Path(args.prefix)/'sources/otelcol-releases-0.163.1.tar.gz'
    try:
        print(json.dumps(inspect(source),sort_keys=True))
    except Exception as e:
        print(json.dumps({'status':'failed','reason':str(e)}),file=sys.stderr)
        sys.exit(1)
