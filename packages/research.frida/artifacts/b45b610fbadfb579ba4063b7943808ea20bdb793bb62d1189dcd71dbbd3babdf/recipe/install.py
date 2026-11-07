#!/usr/bin/env python3
"""Offline installation from byte-locked vendor distributions and wheels."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, os, shutil, stat, tarfile, zipfile

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def unpack_wheel(archive, destination):
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for m in z.infolist():
            parts=PurePosixPath(m.filename).parts
            if not parts or PurePosixPath(m.filename).is_absolute() or '..' in parts:raise ValueError('unsafe wheel entry')
            mode=m.external_attr>>16
            if stat.S_ISLNK(mode):raise ValueError('wheel symlink rejected')
            path=destination.joinpath(*parts)
            if m.is_dir():path.mkdir(parents=True,exist_ok=True);continue
            path.parent.mkdir(parents=True,exist_ok=True)
            with z.open(m) as src,path.open('wb') as out:shutil.copyfileobj(src,out)
            path.chmod(0o755 if (mode&0o111) else 0o644)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--assets',required=True);ap.add_argument('--prefix',required=True);ap.add_argument('--recipe',required=True);args=ap.parse_args()
    recipe=Path(args.recipe).resolve();assets=Path(args.assets).resolve();prefix=Path(args.prefix).resolve();cfg=json.loads((recipe/'config.json').read_text())
    for x in cfg['inputs']:
        p=assets/'raw'/x['file']
        if not p.is_file() or p.stat().st_size!=x['bytes'] or digest(p)!=x['sha256']:raise RuntimeError('input lock mismatch: '+x['file'])
    if cfg['kind'] in ('gtirb','ddisasm','frida'):
        for x in cfg['inputs']:
            archive=assets/'raw'/x['file']
            if x['file'].endswith('.whl'):unpack_wheel(archive,prefix/'python')
            else:
                dest=prefix/'share/upstream'/x['file'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(archive,dest)
    elif cfg['kind']=='dynamorio':
        archive=assets/'raw'/cfg['inputs'][0]['file'];destination=prefix/'sdk';destination.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive) as t:
            for m in t:
                parts=PurePosixPath(m.name).parts[1:]
                if not parts:continue
                rel='/'.join(parts)
                selected=(parts[0] in ('include','bin64') or rel.startswith('lib64/release/') or parts[0].lower().startswith(('license','copyright','acknowledge')))
                if not selected or rel.endswith(('.debug','.a','.so-gdb.py')):continue
                m.name=rel;t.extract(m,destination,filter='data')
        (prefix/'examples').mkdir();shutil.copy2(recipe/'dr_client.c',prefix/'examples/dr_client.c')
    elif cfg['kind']=='intel-pin':
        archive=assets/'raw'/cfg['inputs'][0]['file'];destination=prefix/'kit';destination.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive) as t:
            for m in t:
                parts=PurePosixPath(m.name).parts[1:]
                if not parts:continue
                m.name='/'.join(parts);t.extract(m,destination,filter='data')
    else:raise RuntimeError('unknown install kind')
    (prefix/'CPG-INPUTS.json').write_text(json.dumps(cfg,indent=2)+'\n')
    print(json.dumps({'status':'installed','kind':cfg['kind'],'inputs':len(cfg['inputs'])}))

if __name__=='__main__':main()
