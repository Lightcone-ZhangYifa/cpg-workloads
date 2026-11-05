#!/usr/bin/env python3
"""Build the exact immutable ANL-CESAR XSBench OpenMP CPU source, preserving upstream Makefile."""
import argparse,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--build',type=Path,required=True);p.add_argument('--prefix',type=Path,required=True);p.add_argument('--jobs',type=int,required=True);x=p.parse_args()
s=x.source/'openmp-threading';assert (s/'Makefile').is_file() and (x.source/'LICENSE').is_file() and x.jobs>0
work=x.build/'xsbench-openmp-threading';assert not work.exists();shutil.copytree(s,work,symlinks=True)
cmd=['make',f'-j{x.jobs}','CC=gcc','OPENMP=yes','OPTIMIZE=yes','MPI=no','AML=no']
subprocess.run(cmd,cwd=work,check=True,env={**os.environ,'LC_ALL':'C','OMP_NUM_THREADS':'2'},timeout=180)
bin=work/'XSBench';assert bin.is_file() and os.access(bin,os.X_OK)
install=x.prefix/'bin';install.mkdir(parents=True,exist_ok=True);shutil.copy2(bin,install/'XSBench');(install/'XSBench').chmod(0o755)
notices=x.prefix/'share/doc/XSBench';notices.mkdir(parents=True,exist_ok=True)
for name in ('LICENSE','README.md','CHANGES.txt'): shutil.copy2(x.source/name,notices/name)
print(json.dumps({'status':'built_and_installed','build_from_exact_upstream_makefile':True,'compiler':'gcc','executable_sha256':hashlib.sha256((install/'XSBench').read_bytes()).hexdigest(),'size_bytes':(install/'XSBench').stat().st_size,'bin':str(install/'XSBench'),'upstream': 'ba08e5221af6106252b866e50ea123c69d31a4e2'},sort_keys=True))
