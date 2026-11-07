#!/usr/bin/env python3
"""Offline CPU Legion build. No language/Terra, network or GPU dependency acquisition."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--source',required=True,type=Path)
p.add_argument('--prefix',required=True,type=Path)
p.add_argument('--build',required=True,type=Path)
p.add_argument('--jobs',type=int,default=2)
p.add_argument('--configure-only',action='store_true')
a=p.parse_args()
cmake=os.environ.get('CMAKE','cmake')
b=a.build/'legion-cmake'
cmd=[cmake,'-S',str(a.source),'-B',str(b),'-G','Unix Makefiles',
     '-DCMAKE_BUILD_TYPE=CPGCPU','-DCMAKE_CXX_FLAGS_CPGCPU=-O0',
     '-DCMAKE_C_FLAGS_CPGCPU=-O0','-DBUILD_SHARED_LIBS=ON',
     '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
     '-DBUILD_MARCH=x86-64',
     '-DCMAKE_INSTALL_PREFIX='+str(a.prefix),'-DCMAKE_INSTALL_LIBDIR=lib',
     '-DCMAKE_INSTALL_RPATH=$ORIGIN','-DLegion_BUILD_ALL=OFF',
     '-DLegion_USE_CUDA=OFF','-DLegion_USE_HIP=OFF','-DLegion_USE_GASNet=OFF',
     '-DLegion_USE_HDF5=OFF','-DLegion_USE_HWLOC=OFF','-DLegion_USE_Python=OFF',
     '-DLegion_USE_LLVM=OFF','-DLegion_BUILD_BINDINGS=OFF','-DLegion_BUILD_RUST_PROFILER=OFF',
     '-DREALM_USE_SHM=OFF','-DLegion_MAX_DIM=3','-DLegion_MAX_FIELDS=64',
     '-DLegion_DEFAULT_LOCAL_FIELDS=16','-DLegion_INSTALL_TOOLS=OFF']
commands=[cmd] if a.configure_only else [cmd,[cmake,'--build',str(b),'--parallel',str(max(1,min(a.jobs,1)))],[cmake,'--install',str(b)]]
for command in commands:
    print(json.dumps({'phase':'build','argv':command}),flush=True)
    subprocess.run(command,check=True)
if a.configure_only:
    print('LEGION_CONFIGURED_ONLY_NOT_QUALIFIED')
    raise SystemExit(0)
share=a.prefix/'share/legion-regent'
share.mkdir(parents=True,exist_ok=True)
for name in ('LICENSE.txt','README.md','VERSION'):
    shutil.copy2(a.source/name,share/name)
shutil.copy2(a.source/'realm/LICENSE.txt',share/'Realm-LICENSE.txt')
shutil.copy2(a.source/'language/README.md',share/'Regent-README.md')
(share/'qualification.json').write_text(json.dumps({'source_family':'Legion/Regent','qualified':'Legion C++ single-process CPU 1D logical regions','profile':{'build_type':'CPGCPU','optimization':'-O0','architecture':'x86-64','max_dim':3,'max_fields':64,'local_fields':16},'not_qualified':['Regent/Terra compiler','distributed multi-rank','GPU','performance','2D or 3D consumer behavior']},indent=2)+'\n')
print('LEGION_CPU_INSTALL_OK')
