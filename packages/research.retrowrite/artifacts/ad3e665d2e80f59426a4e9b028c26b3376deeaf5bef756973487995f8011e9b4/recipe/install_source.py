#!/usr/bin/env python3
"""Offline install from exact source and wheel inputs supplied by CPG."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

def install(resource, assets, prefix, recipe):
    config=json.loads((recipe/'install-config.json').read_text())
    source=assets/'upstream'
    prefix.mkdir(parents=True,exist_ok=True)
    (prefix/'lib/python').mkdir(parents=True,exist_ok=True)
    for wheel in config['wheels']:
        path=assets/'wheels'/wheel['filename']
        if path.stat().st_size!=wheel['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=wheel['sha256']:
            raise RuntimeError('Wheel integrity mismatch: '+path.name)
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                pure=Path(name)
                if pure.is_absolute() or '..' in pure.parts:
                    raise RuntimeError('Unsafe wheel member')
            archive.extractall(prefix/'lib/python')
            # zipfile does not restore executable permission bits.
            for member in archive.infolist():
                mode=(member.external_attr>>16)&0o777
                target=prefix/'lib/python'/member.filename
                if mode and target.is_file():target.chmod(mode)
    shutil.copytree(source,prefix/'src'/resource,symlinks=False,dirs_exist_ok=True)
    if resource=='gtirb-rewriting':
        target=prefix/'lib/python/gtirb_rewriting'
        if target.exists():shutil.rmtree(target)
        shutil.copytree(source/'src/gtirb_rewriting',target)
        (target/'version.py').write_text("# Generated from the exact upstream release tag by the CPG installer.\n__version__ = '0.4.1'\n")
    for name in ['tools','bin']:(prefix/name).mkdir(exist_ok=True)
    for name in ['check_resource.py','nop_pass.py']:
        shutil.copy2(recipe/name,prefix/'tools'/name)
    launcher=prefix/'bin'/(resource+'-python')
    launcher.write_text('#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexport PYTHONPATH="$root/lib/python"\nexport PYTHONDONTWRITEBYTECODE=1\nexport PYTHONNOUSERSITE=1\nexec python3 "$@"\n')
    launcher.chmod(0o755)
    if resource=='retrowrite':
        entry=prefix/'bin/retrowrite'
        entry.write_text('#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexport PYTHONPATH="$root/lib/python"\nexport PYTHONDONTWRITEBYTECODE=1\nexport PYTHONNOUSERSITE=1\nexec python3 "$root/src/retrowrite/retrowrite" "$@"\n')
        entry.chmod(0o755)
    (prefix/'SOURCES.json').write_text(json.dumps(config,indent=2)+'\n')
    (prefix/'USAGE.txt').write_text(config['usage']+'\n')
    inventory=[]
    for path in sorted(prefix.rglob('*')):
        if path.is_file() and path.name not in {'.cpg-prefix.json','INVENTORY.json'}:
            inventory.append({'path':path.relative_to(prefix).as_posix(),'bytes':path.stat().st_size,
                              'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (prefix/'INVENTORY.json').write_text(json.dumps(inventory,indent=2)+'\n')
    print(json.dumps({'status':'installed','resource':resource,'files':len(inventory),
                      'installation':'exact upstream Python sources plus locked binary wheel dependencies'}))

if __name__=='__main__':
    install(sys.argv[1],Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]))
