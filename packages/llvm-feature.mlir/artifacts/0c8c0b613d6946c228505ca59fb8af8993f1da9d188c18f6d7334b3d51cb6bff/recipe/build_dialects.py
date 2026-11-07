#!/usr/bin/env python3
"""Build the pinned upstream example against an explicit LLVM SDK, offline."""
from pathlib import Path
import argparse,subprocess,shlex,json,concurrent.futures,time,shutil,os
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--llvm',required=True);p.add_argument('--build',required=True);p.add_argument('--jobs',type=int,default=2);p.add_argument('--fixture');a=p.parse_args()
src=Path(a.source).resolve();llvm=Path(a.llvm).resolve();build=Path(a.build).resolve();build.mkdir(parents=True,exist_ok=True);logs=build/'logs';logs.mkdir(exist_ok=True)
cfg=llvm/'bin/llvm-config';cxx=os.environ.get('CXX','g++')
flags=shlex.split(subprocess.check_output([cfg,'--cxxflags'],text=True))+['-O2','-DNDEBUG','-DHAVE_LLVM_VERSION_MAJOR=23','-I'+str(src/'include'),'-I'+str(build)]
def call(name,args):
 start=time.monotonic();r=subprocess.run([str(x) for x in args],capture_output=True,text=True)
 (logs/(name+'.stdout')).write_text(r.stdout);(logs/(name+'.stderr')).write_text(r.stderr)
 (logs/(name+'.json')).write_text(json.dumps({'argv':[str(x) for x in args],'returncode':r.returncode,'seconds':time.monotonic()-start},indent=2)+'\n')
 if r.returncode: raise RuntimeError(name+'\n'+r.stderr[-5000:])
 return r
def compile(path):
 name=path.relative_to(src).as_posix().replace('/','_');obj=build/(name+'.o')
 call(name,[cxx,*flags,'-c',path,'-o',obj]);return obj
def link(name,objects,components):
 libs=shlex.split(subprocess.check_output([cfg,'--link-static','--libs',*components],text=True))
 ld=shlex.split(subprocess.check_output([cfg,'--ldflags'],text=True))
 syslibs=shlex.split(subprocess.check_output([cfg,'--link-static','--system-libs',*components],text=True))
 # LLVM's SDK encodes build-machine static dependency paths. Bind the host's
 # actual SONAME libraries explicitly, without altering the SDK or source.
 resolved=[]
 for x in syslibs:
  if x.endswith('/libzstd.a'):resolved.append('-l:libzstd.so.1')
  elif x=='-lxml2':resolved.append('-l:libxml2.so.2')
  else:resolved.append(x)
 call(name,[cxx,*objects,*ld,*libs,*resolved,'-o',build/name])
tablegen=sorted((src/'lib/TableGen').glob('*.cpp'))+[src/'utils/llvm-dialects-tblgen.cpp']
with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:objs=list(ex.map(compile,tablegen))
link('llvm-dialects-tblgen',objs,['tablegen','support'])
for which,filename in [('decls','ExampleDialect.h.inc'),('defs','ExampleDialect.cpp.inc')]:
 call('generate-'+which,[build/'llvm-dialects-tblgen',src/'example/ExampleDialect.td','--dialect=xd.ir','-gen-dialect-'+which,'-I',src/'include','-I',llvm/'include','-o',build/filename])
library=sorted((src/'lib/Dialect').glob('*.cpp'))+[src/'example/ExampleDialect.cpp',src/'example/ExampleMain.cpp']
with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:objs=list(ex.map(compile,library))
link('llvm-dialects-example',objs,['asmparser','core','support'])
if a.fixture:
 fixture=Path(a.fixture).resolve();obj=build/'CpgDialectRewrite.o'
 call('CpgDialectRewrite-compile',[cxx,*flags,'-I'+str(src/'example'),'-c',fixture,'-o',obj])
 link('cpg-dialects-rewrite',[x for x in objs if x.name!='example_ExampleMain.cpp.o']+[obj],['asmparser','core','support'])
print(json.dumps({'status':'built','source':str(src),'llvm_version':subprocess.check_output([cfg,'--version'],text=True).strip(),'outputs':[str(build/'llvm-dialects-tblgen'),str(build/'llvm-dialects-example')]}))
