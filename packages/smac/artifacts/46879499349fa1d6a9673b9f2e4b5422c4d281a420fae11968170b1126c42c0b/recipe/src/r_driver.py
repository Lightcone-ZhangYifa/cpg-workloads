"""Run a locally extracted R runtime, with all mutable libraries in an explicit prefix."""
import argparse,os,pathlib,shutil,subprocess

def configure_r(runtime):
 runtime=pathlib.Path(runtime).resolve();rh=runtime/'usr/lib/R'
 for p in (rh/'etc').iterdir():
  if p.is_symlink():
   target=runtime/str(p.readlink()).lstrip('/');p.unlink()
   if target.exists():shutil.copy2(target,p)
   elif p.name=='Renviron':shutil.copy2(rh/'etc/Renviron.ucf',p)
   else:raise RuntimeError('Missing R configuration input: '+str(target))
 wrapper=rh/'bin/R';s=wrapper.read_text();s=s.replace('R_HOME_DIR=/usr/lib/R','R_HOME_DIR="$(cd "$(dirname "$0")/.." && pwd)"',1)
 s=s.replace('R_SHARE_DIR=/usr/share/R/share','R_SHARE_DIR="${R_HOME}/../../share/R/share"').replace('R_INCLUDE_DIR=/usr/share/R/include','R_INCLUDE_DIR="${R_HOME}/../../share/R/include"').replace('R_DOC_DIR=/usr/share/R/doc','R_DOC_DIR="${R_HOME}/../../share/doc/r-base-core"');wrapper.write_text(s)

def environment(runtime,library):
 runtime=pathlib.Path(runtime).resolve();library=pathlib.Path(library).resolve();rh=runtime/'usr/lib/R';env=dict(os.environ)
 values={'R_HOME':rh,'R_SHARE_DIR':runtime/'usr/share/R/share','R_INCLUDE_DIR':runtime/'usr/share/R/include','R_DOC_DIR':runtime/'usr/share/doc/r-base-core','R_LIBS_USER':library,'R_LIBS_SITE':library,'LD_LIBRARY_PATH':rh/'lib','R_ENVIRON_USER':os.devnull,'R_PROFILE_USER':os.devnull,'USE_BUNDLED_LIBUV':'1','MAKEFLAGS':'-j1'}
 env.update({k:str(v) for k,v in values.items()});return env

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--r-root',required=True);p.add_argument('--r-lib',required=True);p.add_argument('--configure',action='store_true');p.add_argument('arguments',nargs=argparse.REMAINDER);a=p.parse_args()
 if a.configure:configure_r(a.r_root)
 args=a.arguments
 if args and args[0]=='--':args=args[1:]
 if args:
  result=subprocess.run([str(pathlib.Path(a.r_root).resolve()/'usr/lib/R/bin/exec/R'),'--vanilla','--slave']+args,env=environment(a.r_root,a.r_lib));raise SystemExit(result.returncode)
