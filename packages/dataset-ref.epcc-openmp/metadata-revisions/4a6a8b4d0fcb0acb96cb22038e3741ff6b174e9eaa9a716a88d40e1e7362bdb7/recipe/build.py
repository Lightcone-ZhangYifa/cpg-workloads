#!/usr/bin/env python3
import argparse,subprocess,pathlib,shutil,json
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--prefix',required=True);p.add_argument('--jobs',type=int,default=2);a=p.parse_args()
src=pathlib.Path(a.source);dest=pathlib.Path(a.prefix);cwd=src/'openmpbench_C_v31';assert (cwd/'Makefile').is_file() and (src/'openmpbench_C_v40/README.md').is_file()
# Exact unmodified original Makefile and original input remain preserved;
# only command-line make variables select existing GNU OpenMP support.
cmd=['make','-C',str(cwd),'-j'+str(min(4,max(1,a.jobs))),'CC=gcc','CFLAGS=-O2 -fopenmp','CFLAGS_CRAY=-O2 -fopenmp','LDFLAGS=-fopenmp','syncbench','schedbench','taskbench']
print('BUILD_ARGV',json.dumps(cmd),flush=True)
subprocess.run(cmd,check=True)
bin=dest/'bin';bin.mkdir(parents=True,exist_ok=True)
for name in ('syncbench','schedbench','taskbench'):
    shutil.copy2(cwd/name,bin/name)
launch=bin/'epcc-openmp'
launch.write_text('#!/bin/sh\nset -eu\nsub=${1:-}\ncase "$sub" in syncbench|schedbench|taskbench) shift;; *) echo "usage: epcc-openmp syncbench|schedbench|taskbench [options]" >&2; exit 64;; esac\nexec "$(dirname "$0")/$sub" "$@"\n')
launch.chmod(0o755)
licenses=dest/'share/licenses';licenses.mkdir(parents=True,exist_ok=True);shutil.copy2(cwd/'Licence.txt',licenses/'EPCC-C-v31-Licence.txt')
notes=dest/'share/doc/epcc-openmp';notes.mkdir(parents=True,exist_ok=True);shutil.copy2(src/'README.md',notes/'README.md');shutil.copy2(cwd/'README.md',notes/'C-v31-README.md')
print('INSTALL_COMPLETED',str(bin),flush=True)
