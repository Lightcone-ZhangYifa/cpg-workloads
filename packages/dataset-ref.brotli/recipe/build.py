#!/usr/bin/env python3
"""Build an explicitly selected native profile from its bundled exact source.
No download, host package installation, privilege activation or target override.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys,time,xml.etree.ElementTree as ET

def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--build',type=Path,required=True);p.add_argument('--prefix',type=Path,required=True);p.add_argument('--jobs',type=int,default=1);a=p.parse_args()
 if a.jobs<1:raise ValueError('jobs must be positive')
 src=a.source.resolve(strict=True);out=a.build.resolve();prefix=a.prefix.resolve();recipe=Path(__file__).resolve().parent;cfg=json.loads((recipe/'config.json').read_text());name=cfg['name']
 stage=out/'native-build';stage.mkdir(exist_ok=False);logs=out/'native-logs';logs.mkdir(exist_ok=False);records=[]
 original={p.relative_to(src).as_posix():sha(p) for p in src.rglob('*') if p.is_file() and not p.is_symlink()}
 def run(label,args,cwd=None,timeout=1800):
  t=time.monotonic()
  with (logs/(label+'.stdout')).open('wb') as f,(logs/(label+'.stderr')).open('wb') as e:
   result=subprocess.run(list(map(str,args)),cwd=cwd,stdout=f,stderr=e,check=False,timeout=timeout,env={**os.environ,'LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'})
  records.append({'name':label,'argv':list(map(str,args)),'cwd':str(cwd) if cwd else None,'returncode':result.returncode,'seconds':time.monotonic()-t});write(logs/'commands.json',records)
  if result.returncode:raise RuntimeError(label+' failed; see '+str(logs/(label+'.stderr')))
 if name in {'zlib','libdeflate','brotli','yyjson'}:
  run('configure',['cmake','-S',src,'-B',stage,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_INSTALL_PREFIX='+str(prefix),'-DCMAKE_INSTALL_LIBDIR=lib','-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON','-DCMAKE_INSTALL_RPATH=$ORIGIN;$ORIGIN/../lib','-DCMAKE_INSTALL_RPATH_USE_LINK_PATH=OFF',*cfg['cmake_flags']])
  run('build',['cmake','--build',stage,'--parallel',a.jobs]);run('test-list',['ctest','--test-dir',stage,'--show-only=json-v1'])
  listed=json.loads((logs/'test-list.stdout').read_text())['tests']
  if not listed:raise RuntimeError('Upstream test list unexpectedly empty')
  run('upstream-tests',['ctest','--test-dir',stage,'--output-on-failure','--output-junit',logs/'upstream-junit.xml','--parallel',a.jobs,'--timeout','300'])
  from ctest_evidence import validate_ctest_evidence
  write(logs/'upstream-summary.json',validate_ctest_evidence(logs/'test-list.stdout',logs/'upstream-junit.xml'))
  run('install',['cmake','--install',stage])
 elif name=='lz4':
  run('build',['make','-C',src,'-j'+str(a.jobs),'allmost']);run('test-build',['make','-C',src/'tests','-j'+str(a.jobs),'unittest','fuzzer','frametest'])
  for label,args in [('unit',['unittest']),('fuzzer',['fuzzer','-i1000','-s1']),('frame',['frametest','-i1000','-s1'])]:run('upstream-'+label,[src/'tests'/args[0],*args[1:]],timeout=300)
  run('install',['make','-C',src,'install','PREFIX='+str(prefix),'LIBDIR='+str(prefix/'lib')])
 elif name=='comd':
  source=src/'src-mpi';shutil.copyfile(source/'Makefile.vanilla',source/'Makefile')
  run('build',['make','-C',source,'-j'+str(a.jobs),'CC=cc','DO_MPI=OFF','OPTFLAGS=-O2'])
  (prefix/'bin').mkdir(exist_ok=True);shutil.copy2(src/'bin/CoMD-serial',prefix/'bin/CoMD-serial')
  shutil.copytree(src/'pots',prefix/'share/comd/pots')
 else:raise ValueError('Unsupported explicit native profile')
 relocation=[]
 for pc in sorted((prefix/'lib/pkgconfig').glob('*.pc')):
  before=pc.read_text();after=before.replace(str(prefix),'${pcfiledir}/../..')
  if before!=after:
   old=sha(pc);pc.write_text(after);relocation.append({'path':str(pc.relative_to(prefix)),'before_sha256':old,'after_sha256':sha(pc),'change':'Replace this installation prefix with the pkg-config file-relative prefix.'})
 write(logs/'pkgconfig-relocation.json',relocation)
 (prefix/'bin').mkdir(exist_ok=True)
 if (recipe/'consumer.c').is_file():
  argv=['cc','-O2','-std=c11','-I'+str(prefix/'include'),str(recipe/'consumer.c'),'-L'+str(prefix/'lib'),'-Wl,-rpath,$ORIGIN/../lib','-Wl,--enable-new-dtags','-o',prefix/'bin/cpg-native-check',*cfg['consumer_link']]
  run('build-independent-consumer',argv)
 notices=prefix/'share/licenses'/name;notices.mkdir(parents=True,exist_ok=True);notice_rows=[]
 for relative,digest in original.items():
  n=Path(relative).name.upper()
  if any(token in n for token in ['LICENSE','COPYING','COPYRIGHT','NOTICE']):
   p=src/relative;target=notices/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);notice_rows.append({'path':relative,'sha256':digest,'bytes':p.stat().st_size})
 if not notice_rows:raise RuntimeError('No original upstream licensing notices retained')
 write(prefix/'share/compiler-playground/native-profile.json',{'scope':'Selected native profile; original source identity retained; no benchmark qualification','name':name,'source':cfg['source'],'original_definition_sha256':cfg['original_definition_sha256'],'compiler_abi':cfg['target'],'configuration':cfg['cmake_flags'],'license_files':notice_rows,'benchmark_qualification':False})
 changed=[rel for rel,d in original.items() if not (src/rel).is_file() or sha(src/rel)!=d]
 write(logs/'original-source-check.json',{'original_files':len(original),'changed_original_files':changed,'generated_files_are_build_outputs':True})
 if changed:raise RuntimeError('Build modified retained original file content: '+', '.join(changed[:5]))
 print(json.dumps({'status':'passed','profile':name,'original_files_unchanged':len(original),'commands':len(records)}))
if __name__=='__main__':main()
