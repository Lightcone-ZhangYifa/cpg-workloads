#!/usr/bin/env python3
"""Native CPU-serial Quicksilver from all 159 original files, without source edits.

Host compatibility: explicit GCC/C++11, forced stdint header because original
MC_Cell_State.hh does not include it; generated git_hash.hh from exact pin,
and empty .depend in isolated BUILD COPY because makedepend is not installed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

REV='eb68bb8d6fc53de1f65011d4e79ff2ed0dd60f3b'
ORIGINAL_SHA='47b61b3441c6f8c334be3ebe7198232f6b07aa5ea5bbb9ec6cece4bed1e18a03'

def sha(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def inventory(root):
    result={}
    for p in sorted(root.rglob('*')):
        mode=p.lstat().st_mode
        if stat.S_ISDIR(mode):continue
        if not stat.S_ISREG(mode):raise RuntimeError('Expected no original symlinks/special files: '+str(p))
        result[p.relative_to(root).as_posix()]={'bytes':p.stat().st_size,'sha256':sha(p)}
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--prefix',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args()
    assert 1<=args.jobs<=3
    src=args.source.resolve(strict=True)
    build=args.build.resolve()
    prefix=args.prefix.resolve()
    assert (src/'src/Makefile').is_file() and (src/'LICENSE.md').is_file()
    assert src not in (build,prefix) and src not in build.parents and src not in prefix.parents
    before=inventory(src)
    if len(before)!=159:raise RuntimeError('Fixed original 159 files missing')
    work=build/'complete-upstream-source-copy'
    shutil.copytree(src,work)
    make_src=work/'src'
    # Existing source is immutable. These generated headers and empty makedepend
    # guard only touch an entirely independent disposable build copy.
    (make_src/'.depend').touch(exist_ok=False)
    logs=build/'logs';logs.mkdir(parents=True,exist_ok=False)
    command=['make','-C',str(make_src),'-j'+str(args.jobs),'CXX=g++','CXXFLAGS=-std=c++11 -O2',
             'CPPFLAGS=-include cstdint','LDFLAGS=',f'GITHASH={REV}','GITVERS=pinned-source-archive','qs']
    started=time.monotonic()
    with (logs/'native-build.stdout').open('wb') as out,(logs/'native-build.stderr').open('wb') as err:
        completed=subprocess.run(command,stdout=out,stderr=err,env={**os.environ,'LC_ALL':'C'},timeout=900,check=False)
    receipt={'build_argv':command,'returncode':completed.returncode,'elapsed_seconds':round(time.monotonic()-started,3)}
    (logs/'commands.json').write_text(json.dumps(receipt,indent=2)+'\n')
    if completed.returncode:
        raise RuntimeError('Quicksilver full unmodified upstream C++ build failed; see retained logs')
    binary=make_src/'qs'
    assert binary.is_file() and os.access(binary,os.X_OK)
    target=prefix/'bin/qs';target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(binary,target);target.chmod(0o755)
    license_path=prefix/'share/licenses/quicksilver/LICENSE.md'
    license_path.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src/'LICENSE.md',license_path)
    for name in ['AllAbsorb/allAbsorb.inp','AllEscape/allEscape.inp']:
        original=src/'Examples'/name
        target=prefix/'share/quicksilver/Examples'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original,target)
    if inventory(src)!=before:
        raise RuntimeError('Native build mutated original exact source files')
    profile={
      'schema_version':1,'host_os':'debian-13','arch':'x86_64','processor':'host_cpu',
      'source_git_commit':REV,'original_source_archive_sha256':ORIGINAL_SHA,
      'input_total_file_count':159,'source_unchanged':True,
      'build_command':command,'source_build_duration_seconds':receipt['elapsed_seconds'],
      'compatibility_fix':'GCC14 forced -include cstdint; original header omitted direct include',
      'makedepend_unavailable':'Empty .depend file created in separate build copy; upstream dependency generator not invoked',
      'serial_mpi':False,'openmp':False,'gpu':False,
      'binary_sha256':sha(prefix/'bin/qs'),
      'license_file_sha256':sha(license_path),
      'original_target_ubuntu24_qualified':False,
      'full_physical_correctness_oracle':False,'official_benchmark_qualified':False,
      'oci_qualified':False,'hardware_qualified':False,
      'license_review_required':True,
    }
    r=prefix/'share/compiler-playground/quicksilver-native-profile.json'
    r.parent.mkdir(parents=True,exist_ok=True)
    r.write_text(json.dumps(profile,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'status':'passed','source_members':len(before),'source_unchanged':True,
                     'binary_sha256':profile['binary_sha256'],
                     'original_target_qualified':False}))

if __name__=='__main__':main()
