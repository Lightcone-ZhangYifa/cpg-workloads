#!/usr/bin/env python3
"""Install verified immutable inputs to an isolated prefix without network access."""
import argparse,hashlib,json,pathlib,subprocess,tarfile,shutil,sys
if sys.flags.optimize:raise SystemExit('Optimized Python disables required validation; use normal python3 without -O or PYTHONOPTIMIZE.')
p=argparse.ArgumentParser();p.add_argument('--inputs',required=True,type=pathlib.Path);p.add_argument('--prefix',required=True,type=pathlib.Path);p.add_argument('--kind',choices=['rust','clang','all'],default='all');a=p.parse_args()
a.inputs=a.inputs.resolve();a.prefix=a.prefix.resolve()
assert not a.prefix.is_relative_to(a.inputs) and not a.inputs.is_relative_to(a.prefix), 'SDK prefix and immutable inputs must be disjoint'
assert not a.prefix.exists() or not any(a.prefix.iterdir()), 'SDK prefix must be fresh or empty'
a.prefix.mkdir(parents=True,exist_ok=True)
installed=[]
if a.kind in ['rust','all']:
    for rec in json.loads((a.inputs/'rust-components.json').read_text()):
        src=a.inputs/rec['url'].split('/')[-1]
        assert hashlib.sha256(src.read_bytes()).hexdigest()==rec['sha256'],f'Input hash mismatch: {src}'
        unpack=a.prefix/'unpack';unpack.mkdir(exist_ok=True)
        with tarfile.open(src) as tf:tf.extractall(unpack,filter='data')
        tree=unpack/src.name[:-7]
        subprocess.run(['bash',str(tree/'install.sh'),'--prefix='+str(a.prefix/'rust'),'--disable-ldconfig'],check=True)
        shutil.rmtree(tree)
        installed.append({'component':rec['name'],'sha256':rec['sha256']})
    (a.prefix/'unpack').rmdir()
if a.kind in ['clang','all']:
    for rec in json.loads((a.inputs/'clang18/inputs-lock.json').read_text()):
        src=a.inputs/'clang18'/rec['filename']
        assert hashlib.sha256(src.read_bytes()).hexdigest()==rec['sha256'],f'Input hash mismatch: {src}'
        subprocess.run(['dpkg-deb','-x',str(src),str(a.prefix/'clang')],check=True)
        installed.append({'component':rec['package'],'sha256':rec['sha256']})
(a.prefix/'installed-inputs.json').write_text(json.dumps(installed,indent=2)+'\n')
print(json.dumps({'prefix':str(a.prefix),'rust_bin':str(a.prefix/'rust/bin'),'clang_bin':str(a.prefix/'clang/usr/bin'),'clang_library_path':str(a.prefix/'clang/usr/lib/x86_64-linux-gnu'),'components':installed},indent=2))
