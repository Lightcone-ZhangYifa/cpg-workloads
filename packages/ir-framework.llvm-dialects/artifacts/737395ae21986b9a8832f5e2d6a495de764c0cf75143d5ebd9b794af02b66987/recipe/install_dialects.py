"""Source method: independent upstream source/build/install trees, no downloads."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys
if sys.flags.optimize:raise RuntimeError('Source qualification requires Python optimization disabled')
p=argparse.ArgumentParser();p.add_argument('--assets',required=True);p.add_argument('--prefix',required=True);p.add_argument('--build',required=True);p.add_argument('--jobs',type=int,default=2);a=p.parse_args()
recipe=Path(__file__).resolve().parent;assets=Path(a.assets).resolve();prefix=Path(a.prefix).resolve();build=Path(a.build).resolve();sdk=assets/'llvm-sdk';src=assets/'upstream'
lock=json.loads((sdk/'profile-lock.json').read_text())
for row in lock['files']:
 path=sdk/row['path']
 if path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('SDK integrity mismatch: '+row['path'])
if subprocess.check_output([sdk/'bin/llvm-config','--version'],text=True).strip()!='23.1.4':raise RuntimeError('SDK version differs from fixed LLVM 23.1.4')
subprocess.run([sys.executable,recipe/'build_dialects.py','--source',src,'--llvm',sdk,'--build',build/'compiler-build','--jobs',str(a.jobs),'--fixture',recipe/'checks/CpgDialectRewrite.cpp'],check=True)
(prefix/'bin').mkdir(parents=True,exist_ok=True)
for name in ['llvm-dialects-tblgen','llvm-dialects-example','cpg-dialects-rewrite']:shutil.copy2(build/'compiler-build'/name,prefix/'bin'/name)
shutil.copytree(src,prefix/'share/llvm-dialects')
shutil.copytree(recipe/'checks',prefix/'checks')
(prefix/'source-build.json').write_text(json.dumps({'method':'source','upstream_commit':'4d0dfd05c436ea49aaaa6ad010bb3cf64da0ddb9','llvm_version':'23.1.4','source_unmodified':True,'build_profile':'Direct C++ compile/link of upstream source, not full CMake/lit matrix','host_shared_library_bindings':['libzstd.so.1','libxml2.so.2']},indent=2)+'\n')
