#!/usr/bin/env python3
"""Install only already frozen local inputs; never resolves or downloads online."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import venv


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True)
    ap.add_argument('--prefix',required=True);ap.add_argument('--build',required=True)
    a=ap.parse_args();recipe=Path(__file__).resolve().parent
    config=json.loads((recipe/'install-config.json').read_text())
    source=Path(a.source);prefix=Path(a.prefix);build=Path(a.build)
    for row in config['additional_inputs']:
        p=recipe/'inputs'/row['filename']
        if p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:
            raise ValueError('frozen extra input mismatch: '+row['filename'])
    kind=config['kind']
    if kind in ['python','cdash']:
        wheels=build/'wheelhouse';wheels.mkdir(exist_ok=True)
        for row in config['additional_inputs']:
            if row['filename'].endswith('.whl'):
                shutil.copy2(recipe/'inputs'/row['filename'],wheels/row['filename'])
        if kind=='python':
            shutil.copy2(source,wheels/config['main_filename']);target=prefix
        else:
            target=prefix/'tools/cmake'
            shutil.copytree(source,prefix/'share/cdash',symlinks=True,dirs_exist_ok=True)
        venv.EnvBuilder(with_pip=True,symlinks=False).create(target)
        subprocess.run([str(target/'bin/python'),'-m','pip','install','--disable-pip-version-check',
                        '--no-index','--find-links',str(wheels),'--require-hashes',
                        '-r',str(recipe/'requirements.lock')],check=True)
        subprocess.run([str(target/'bin/python'),'-m','pip','check'],check=True)
    elif kind=='jtreg':
        shutil.copytree(source,prefix/'jtreg',dirs_exist_ok=True)
        jdk=recipe/'inputs'/config['jdk_archive']
        unpack=build/'jdk-unpack';unpack.mkdir()
        with tarfile.open(jdk) as t:t.extractall(unpack,filter='data')
        roots=list(unpack.iterdir())
        if len(roots)!=1 or not roots[0].is_dir():raise ValueError('unexpected JDK archive layout')
        shutil.copytree(roots[0],prefix/'jdk',symlinks=True)
        for name in ['jtreg','jtdiff']:
            path=prefix/'jtreg/bin'/name
            if path.exists():path.chmod(0o755)
        bindir=prefix/'bin';bindir.mkdir(exist_ok=True)
        launcher='''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export JAVA_HOME="$root/jdk"
export JTREG_HOME="$root/jtreg"
export JTREG_JAVA="$root/jdk/bin/java"
exec sh "$root/jtreg/bin/jtreg" "$@"
'''
        (bindir/'jtreg').write_text(launcher);(bindir/'jtreg').chmod(0o755)
    else:raise ValueError(kind)
    print(json.dumps({'status':'installed','kind':kind,'offline':True,'prefix':str(prefix),
                      'input_count':1+len(config['additional_inputs']),
                      'source_compiled':False}))


if __name__=='__main__':main()
