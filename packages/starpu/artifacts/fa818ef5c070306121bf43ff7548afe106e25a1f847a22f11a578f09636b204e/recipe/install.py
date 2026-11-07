#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--prefix',required=True,type=Path);p.add_argument('--build',required=True,type=Path);p.add_argument('--jobs',type=int,default=1)
a=p.parse_args()
a.source=a.source.resolve();a.prefix=a.prefix.resolve();a.build=a.build.resolve()
paths=(a.source,a.prefix,a.build)
if any(x==y or x in y.parents or y in x.parents for i,x in enumerate(paths) for y in paths[i+1:]):
    raise SystemExit('source, build and install prefix must be disjoint')
b=a.build/'starpu-autotools';b.mkdir(parents=True,exist_ok=True)
# Explicit baseline x86-64 ISA; do not inherit host-specific optimisation flags.
flags='-O1 -march=x86-64 -mtune=generic'
env=dict(os.environ,CFLAGS=flags,CXXFLAGS=flags,CPPFLAGS='',LDFLAGS='')
config=[str(a.source/'configure'),'--prefix='+str(a.prefix),'--disable-static','--enable-shared','--disable-cuda','--disable-opencl','--disable-hip','--disable-mpi','--disable-mpi-master-slave','--disable-tcpip-master-slave','--disable-fortran','--disable-build-doc','--disable-build-examples','--disable-build-tests','--disable-socl','--disable-openmp','--disable-fxt','--without-hwloc','--disable-blas-lib','--disable-starpufft','--disable-starpupy','--disable-starpurm','--disable-julia','--disable-papi','--disable-glpk','--disable-hdf5','--disable-max-fpga','--disable-gdb','--enable-maxcpus=256']
for cmd in (config,['make','-j'+str(max(1,min(a.jobs,1)))],['make','install']):
    print(json.dumps({'argv':cmd}),flush=True)
    subprocess.run(cmd,cwd=b,env=env,check=True)
share=a.prefix/'share/starpu-cpg';share.mkdir(parents=True,exist_ok=True)
for name in ('COPYING.LGPL','AUTHORS','README.md','STARPU-VERSION'):
    if (a.source/name).is_file():shutil.copy2(a.source/name,share/name)
# Publish the explicit CPU runtime profile. Auxiliary upstream tools embed the
# build prefix in RUNPATH and are outside this profile, so they are not shipped.
# Keep the unmodified shared runtime, public headers, one current .pc and notices.
omitted=[]
def omit(path):
    members=[path]+(sorted(path.rglob('*')) if path.is_dir() and not path.is_symlink() else [])
    for member in members:
        if member.is_symlink():
            omitted.append(dict(path=str(member.relative_to(a.prefix)),kind='symlink',target=os.readlink(member)))
        elif member.is_file():
            omitted.append(dict(path=str(member.relative_to(a.prefix)),kind='file',bytes=member.stat().st_size,sha256=hashlib.sha256(member.read_bytes()).hexdigest()))
    if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
    else:path.unlink()
for path in sorted(a.prefix.iterdir()):
    if path.name not in ('.cpg-prefix.json','include','lib','share'):omit(path)
for path in sorted((a.prefix/'share').iterdir()):
    if path.name!='starpu-cpg':omit(path)
for path in sorted((a.prefix/'lib').iterdir()):
    if path.name!='pkgconfig' and not path.name.startswith('libstarpu-1.4.so'):omit(path)
for path in sorted((a.prefix/'lib/pkgconfig').iterdir()):
    if path.name!='starpu-1.4.pc':omit(path)
# Installed pkg-config metadata must resolve relative to B after prefix A is
# removed. Upstream sources and the locked archive are left byte-for-byte intact.
pc_changes=[]
for path in sorted((a.prefix/'lib/pkgconfig').glob('*.pc')):
    before=path.read_text()
    after=re.sub(r'^prefix=.*$',r'prefix=${pcfiledir}/../..',before,flags=re.MULTILINE)
    after=after.replace(str(a.prefix),'${prefix}')
    if after==before:raise SystemExit('expected absolute generated pkg-config prefix: '+str(path))
    path.write_text(after)
    pc_changes.append(str(path.relative_to(a.prefix)))
generated=(b/'Makefile').read_text()
if '-march=native' in generated or '-mtune=native' in generated:
    raise SystemExit('unexpected host-specific ISA in generated Makefile')
versions={}
for name in ('gcc','g++','make'):
    command=env.get('CC' if name=='gcc' else 'CXX' if name=='g++' else '__unused__',name)
    cp=subprocess.run([command,'--version'],text=True,capture_output=True,check=True)
    versions[name]=dict(command=command,version=cp.stdout.splitlines()[0])
provenance=dict(schema_version=1,scope='CPU shared runtime, C headers and relative pkg-config metadata; no GPU/MPI/Fortran/auxiliary-tool qualification',compiler_flags=flags,configure_options=config[1:],host_tools=versions,source_build_install_disjoint=True,pkgconfig_rewritten_relative=pc_changes,removed_libtool_metadata=True,omitted_from_runtime_profile=omitted)
(share/'cpg-build-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
print('STARPU_CPU_INSTALL_OK')
