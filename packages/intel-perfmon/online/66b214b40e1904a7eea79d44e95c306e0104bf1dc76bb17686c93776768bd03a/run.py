#!/usr/bin/env python3
"""Exact-original Intel PMU tables: bounded source fetch or hermetic offline package reproduction.

No deployment-time fetching occurs in --offline mode. The caller supplies an
existing content-addressed original source archive or explicitly opts into HTTPS.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
import urllib.request

from compiler_playground.packages.archive import pack, verify_package


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_raw(path, source):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not stat.S_ISREG(p.stat().st_mode):
        raise ValueError('Source archive missing, symlinked or nonregular')
    if p.stat().st_size != source['bytes']:
        raise ValueError('Pinned source archive byte count mismatch')
    if digest(p) != source['sha256']:
        raise ValueError('Pinned source archive SHA256 mismatch')
    return p


def acquire(source, cache, offline):
    cache=Path(cache).resolve(); d=cache/source['sha256'][:2]; candidate=d/source['sha256']
    if candidate.is_file() or candidate.is_symlink():
        return verify_raw(candidate,source)
    if offline:
        raise ValueError('Pinned archive not present in cache; offline mode forbids network')
    if not source['url'].startswith('https://'):
        raise ValueError('Pinned HTTPS URL required')
    d.mkdir(parents=True,exist_ok=True)
    # Fetch to a temporary regular file; reject an oversized response early.
    with tempfile.NamedTemporaryFile(prefix='.cpg-pinned-',dir=d,delete=False) as stream:
        temporary=Path(stream.name)
        try:
            req=urllib.request.Request(source['url'],headers={'User-Agent':'CompilerPlayground-Locked-Original/1.0'})
            with urllib.request.urlopen(req,timeout=30) as incoming:
                remaining=source['bytes']
                while True:
                    chunk=incoming.read(min(1048576,remaining+1))
                    if not chunk:break
                    if len(chunk)>remaining:
                        raise ValueError('Live origin exceeded pinned transfer bound')
                    stream.write(chunk);remaining-=len(chunk)
            stream.flush();os.fsync(stream.fileno())
            verify_raw(temporary,source)
            os.replace(temporary,candidate)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    return candidate


def unpack_full_original(archive, folder, source):
    """Reject unsafe tar entries; reconstruct every original regular file, unmodified."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    root_name=None;observed=[]
    with tarfile.open(archive,'r:gz') as stream:
        members=stream.getmembers()
        if len(members)>30000:raise ValueError('Bound exceeded for archive members')
        for item in members:
            parts=PurePosixPath(item.name).parts
            if not parts or any(x in ('','..','.') for x in parts):
                raise ValueError('Invalid tar member path')
            if root_name is None:root_name=parts[0]
            if parts[0]!=root_name:raise ValueError('Tar archive has multiple roots')
            if not (item.isdir() or item.isfile()):
                raise ValueError('Nonregular or symlinked source item forbidden: '+item.name)
            relative=PurePosixPath(*parts[1:])
            if not relative.parts:continue
            target=folder.joinpath(*relative.parts)
            if item.isdir():
                target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():raise ValueError('Duplicated tar member '+item.name)
                with stream.extractfile(item) as src, target.open('xb') as out:
                    shutil.copyfileobj(src,out,length=1024*1024)
                if target.stat().st_size!=item.size:
                    raise ValueError('Tar file truncated: '+item.name)
                target.chmod(item.mode&0o777)
                observed.append(str(relative))
    if len(observed)<100 or not (folder/'mapfile.csv').is_file():
        raise ValueError('Incomplete pinned Intel PMU table tree')
    return {'original_root':root_name,'files':len(observed),'no_omitted_file_filtering':True}


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('action',choices=['fetch','prepare']);p.add_argument('--cache',required=True);p.add_argument('--output');p.add_argument('--offline',action='store_true');p.add_argument('--recipe',default=str(Path(__file__).parent));a=p.parse_args(argv)
    root=Path(a.recipe).resolve();spec=json.loads((root/'package.json').read_text());prov=json.loads((root/'provenance.json').read_text())
    if spec['id']!='intel-perfmon' or len(spec['sources'])!=1 or spec['provider']!='material':
        raise ValueError('Frozen original resource identity mismatch')
    source=spec['sources'][0]
    archive=acquire(source,Path(a.cache),a.offline)
    if a.action=='fetch':
        print(json.dumps({'status':'pinned-input-present','sha256':source['sha256'],'bytes':source['bytes'],'source_url':source['url']}));return
    if a.output is None:raise ValueError('--output required for prepare')
    output=Path(a.output)
    if output.exists():raise FileExistsError(output)
    with tempfile.TemporaryDirectory(prefix='cpg-pmu-online-') as temp:
        folder=Path(temp)/'payload'
        full=unpack_full_original(archive,folder,source)
        result=pack(spec,output,method='material',payload=folder,recipe_dir=root/'recipe',provenance=prov)
    verify_package(output,expected_sha256=result['sha256'],expected_bytes=result['bytes'])
    print(json.dumps({'status':'offline-reproduced' if a.offline else 'prepared','source':source['sha256'],'original_completeness':full,'package':result},sort_keys=True))

if __name__=='__main__':main()
