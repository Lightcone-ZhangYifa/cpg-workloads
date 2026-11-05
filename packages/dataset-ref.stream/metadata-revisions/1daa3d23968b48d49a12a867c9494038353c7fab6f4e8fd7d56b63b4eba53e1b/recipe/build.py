#!/usr/bin/env python3
import argparse, subprocess, shutil, pathlib, json, os
p=argparse.ArgumentParser(); p.add_argument('--source',required=True); p.add_argument('--prefix',required=True); p.add_argument('--jobs',type=int,default=2); a=p.parse_args()
src=pathlib.Path(a.source); dst=pathlib.Path(a.prefix); bindir=dst/'bin';bindir.mkdir(parents=True,exist_ok=True)
assert src.is_dir() and (src/'stream.c').is_file(), 'source closure missing pinned root file'
if 'stream'=='stream':
    argv=['gcc','-O2','-fopenmp','-DSTREAM_ARRAY_SIZE=1000000','-DNTIMES=10','-o',str(bindir/'stream'),str(src/'stream.c')]
    print('BUILD_ARGV',json.dumps(argv),flush=True);subprocess.run(argv,check=True)
    license_file=src/'LICENSE.txt';(dst/'share/licenses').mkdir(parents=True,exist_ok=True);shutil.copy2(license_file,dst/'share/licenses/STREAM-LICENSE.txt')
else:
    argv=['make','-C',str(src/'openmp-threading'),'-j'+str(min(4,max(1,a.jobs))),'CC=gcc']
    print('BUILD_ARGV',json.dumps(argv),flush=True);subprocess.run(argv,check=True)
    shutil.copy2(src/'openmp-threading/rsbench',bindir/'rsbench')
    share=dst/'share/doc/rsbench';share.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src/'README.md',share/'README.md')
print('INSTALL_COMPLETED',str(bindir/'stream'),flush=True)
