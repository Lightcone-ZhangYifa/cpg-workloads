#!/usr/bin/env python3
"""Acquire the EXACT pinned DejaGNU 1.6.3 source material, without guessing HEAD.

The locked upstream URL and source bytes are read from an immutable original-source
lock embedded in the package recipe. Default fetch is real HTTPS GET. `--test-url`
requires --allow-loopback-test and only permits loopback HTTP, so a successful
local recipe test cannot be confused with upstream acquisition.

This is a material acquisition recipe, not DejaGNU runtime installation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from urllib.parse import urlparse
from urllib.request import Request,urlopen

DEFAULT_MANIFEST=Path(__file__).resolve().parent/'material-manifest.json'


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as fp:
        for block in iter(lambda:fp.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def check_manifest(manifest):
    m=json.loads(Path(manifest).read_bytes())
    if m.get('resource_id')!='dejagnu-source' or m.get('kind')!='complete_original_source_archive_static_material':
        raise ValueError('Expected original complete DejaGNU source material manifest')
    lock=m['original_source_lock']
    if lock['id']!='dejagnu-source' or lock['url']!='https://ftp.gnu.org/gnu/dejagnu/dejagnu-1.6.3.tar.gz':
        raise ValueError('Original URL identity differs from pinned DejaGNU 1.6.3 source')
    if lock['sha256']!='87daefacd7958b4a69f88c6856dbd1634261963c414079d0c371f589cd66a2e3' or lock['bytes']!=622059:
        raise ValueError('Pinned exact SHA256/bytes mismatch')
    if lock['extract'] is not True or lock['strip_root'] is not True or lock['material_path']!='sources/dejagnu':
        raise ValueError('Unexpected original extraction contract')
    return m,lock


def verify_extract(archive,destination,manifest):
    rows=manifest['members']
    assert len(rows)==215
    expected={r['path']:r for r in rows}
    assert len(expected)==len(rows)
    seen=set()
    with tarfile.open(archive,mode='r:gz') as tar:
        entries=tar.getmembers()
        if len(entries)!=216:raise ValueError('Original upstream member count changed')
        for m in entries:
            if m.type not in (tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.DIRTYPE):
                raise ValueError('Unsafe link/device/PAX member: '+m.name)
            path=PurePosixPath(m.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='dejagnu-1.6.3':
                raise ValueError('Archive escapes locked root')
            if len(path.parts)==1:
                if not m.isdir():raise ValueError('Locked root is not a directory')
                continue
            stripped=PurePosixPath(*path.parts[1:]).as_posix()
            if stripped not in expected or stripped in seen:raise ValueError('Unexpected or repeated source archive member')
            seen.add(stripped)
            row=expected[stripped]
            if row['type']!=('file' if m.isfile() else 'directory') or row['mode']!=(m.mode&0o777):
                raise ValueError('Member identity or permissions do not match full locked archive: '+stripped)
            if m.isfile():
                if row['bytes']!=m.size:raise ValueError('Source member byte count mismatch: '+stripped)
                data=tar.extractfile(m).read()
                if hashlib.sha256(data).hexdigest()!=row['sha256'] or len(data)!=row['bytes']:
                    raise ValueError('Source member SHA256 mismatch: '+stripped)
            else:data=None
            out=destination/stripped
            if m.isdir():out.mkdir(parents=True,exist_ok=True)
            else:
                out.parent.mkdir(parents=True,exist_ok=True)
                with out.open('xb') as fp:fp.write(data)
            out.chmod(row['mode'])
    if seen != set(expected):raise ValueError('Incomplete source contents')
    actual={p.relative_to(destination).as_posix() for p in destination.rglob('*')}
    if actual != set(expected):raise ValueError('Installed material tree does not match manifest')
    return {'entries':len(rows),'regular_files':sum(r['type']=='file' for r in rows),
            'directories':sum(r['type']=='directory' for r in rows)}


def acquire(manifest_path,output,test_url=None,allow_loopback_test=False):
    manifest,lock=check_manifest(manifest_path)
    output=Path(output).absolute()
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    if output.parent.is_symlink():raise ValueError('Output parent must be a normal directory')
    output.parent.mkdir(parents=True,exist_ok=True)
    url=lock['url']
    is_test=test_url is not None
    if is_test:
        p=urlparse(test_url)
        if not allow_loopback_test or p.scheme!='http' or p.hostname not in {'localhost','127.0.0.1','::1'}:
            raise ValueError('Only explicit loopback-only test URLs are accepted; original URL is never changed')
        url=test_url
    request=Request(url,headers={'User-Agent':'compiler-playground-dejagnu-material-recipe/1.0',
                                'Accept':'application/gzip,application/octet-stream'})
    with tempfile.TemporaryDirectory(prefix='.dejagnu-acquire-',dir=output.parent) as tmp:
        stage=Path(tmp)/'ready'
        stage.mkdir()
        archive=stage/'original-dejagnu-1.6.3.tar.gz'
        transferred=0
        h=hashlib.sha256()
        with urlopen(request,timeout=25) as response,archive.open('xb') as dest:
            final_url=response.geturl()
            final_parsed=urlparse(final_url)
            if is_test:
                if final_parsed.scheme!='http' or final_parsed.hostname not in {'localhost','127.0.0.1','::1'}:
                    raise ValueError('Loopback test must not redirect to a non-loopback URL')
            elif final_parsed.scheme!='https':raise ValueError('Upstream source transfer must remain HTTPS')
            content_length=response.headers.get('Content-Length')
            if content_length is not None and int(content_length)!=lock['bytes']:
                raise ValueError('Content-Length differs from pinned source size')
            while True:
                piece=response.read(min(64*1024,lock['bytes']+1-transferred))
                if not piece:break
                transferred+=len(piece)
                if transferred>lock['bytes']:raise ValueError('Source transfer exceeded locked byte limit')
                h.update(piece)
                dest.write(piece)
        if transferred!=lock['bytes'] or h.hexdigest()!=lock['sha256']:
            raise ValueError('Source GET differs from exact SHA256/size lock')
        unpack=stage/lock['material_path']
        unpack.mkdir(parents=True)
        tree=verify_extract(archive,unpack,manifest)
        receipt={'resource_id':lock['id'],'source_url_original':lock['url'],
                 'actual_get_url':final_url,'source_sha256':lock['sha256'],
                 'source_bytes':transferred,'validation':'exact_hash_size_all_members_modes',
                 'recipe_transport':'loopback_test' if is_test else 'verified_remote_https',
                 'actual_remote_upstream_acquisition':not is_test,
                 'original_catalog_identity_unchanged':True,'complete_source_tree':tree,
                 'native_tool_functionality_qualified':False}
        (stage/'acquisition-receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
        os.replace(stage,output)
    return receipt


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest',type=Path,default=DEFAULT_MANIFEST)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--test-url')
    ap.add_argument('--allow-loopback-test',action='store_true')
    args=ap.parse_args()
    receipt=acquire(args.manifest,args.output,args.test_url,args.allow_loopback_test)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
