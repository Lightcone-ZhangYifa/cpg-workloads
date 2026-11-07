#!/usr/bin/env python3
"""Build one declared native resource from already acquired, verified local inputs."""
import argparse, json, os, pathlib, shutil, subprocess, sys, zipfile

def run(argv, cwd=None, env=None):
    print('+', ' '.join(str(x) for x in argv),flush=True)
    subprocess.run([str(x) for x in argv],cwd=cwd,env=env,check=True)
def copy_notices(src,dst,label):
    out=dst/'share/licenses'/label;out.mkdir(parents=True,exist_ok=True)
    for pattern in ['LICENSE*','COPYING*','NOTICE*']:
        for p in src.glob(pattern):
            if p.is_file():shutil.copy2(p,out/p.name)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--resource',required=True);ap.add_argument('--assets',type=pathlib.Path,required=True);ap.add_argument('--build',type=pathlib.Path,required=True);ap.add_argument('--prefix',type=pathlib.Path,required=True);ap.add_argument('--jobs',type=int,default=2);a=ap.parse_args()
    recipe=pathlib.Path(__file__).resolve().parent;p=a.prefix.resolve();assets=a.assets.resolve();b=a.build.resolve();p.mkdir(parents=True,exist_ok=True);b.mkdir(parents=True,exist_ok=True)
    jobs=min(a.jobs,3)
    if a.resource=='elfio':
        src=assets/'elfio';(p/'include').mkdir(exist_ok=True);(p/'bin').mkdir(exist_ok=True)
        for d in ['elfio','ario']:shutil.copytree(src/d,p/'include'/d)
        copy_notices(src,p,'ELFIO-ARIO')
        run(['g++','-std=c++17','-O2','-I'+str(p/'include'),recipe/'elfio_probe.cpp','-o',p/'bin/cpg-elfio-probe'])
    elif a.resource=='intel-xed':
        src=assets/'intel-xed';mbuild=assets/'intel-mbuild';env=os.environ.copy();env['PYTHONPATH']=str(mbuild)
        run([sys.executable,'-u',src/'mfile.py','--shared','--prefix='+str(p),'-j',str(jobs),'examples','install'],cwd=src,env=env)
        copy_notices(src,p,'Intel-XED');copy_notices(mbuild,p,'mbuild')
        (p/'bin').mkdir(exist_ok=True)
        run(['gcc','-std=c11','-O2','-DUSE_XED','-I'+str(p/'include'),recipe/'native_probe.c','-L'+str(p/'lib'),'-lxed','-Wl,-rpath,$ORIGIN/../lib','-o',p/'bin/cpg-intel-xed-probe'])
    elif a.resource=='zydis':
        src=assets/'zydis';zycore=assets/'zycore';wheel=next((assets/'inputs').glob('cmake*.whl'));cmroot=b/'cmake-wheel'
        with zipfile.ZipFile(wheel) as z:z.extractall(cmroot)
        for exe in (cmroot/'cmake/data/bin').iterdir():exe.chmod(0o755)
        cmake=cmroot/'cmake/data/bin/cmake';out=b/'zydis-build'
        run([cmake,'-S',src,'-B',out,'-DCMAKE_BUILD_TYPE=Release','-DZYAN_ZYCORE_PATH='+str(zycore),'-DZYDIS_BUILD_EXAMPLES=ON','-DZYDIS_BUILD_TOOLS=ON','-DZYDIS_BUILD_TESTS=ON','-DZYDIS_BUILD_DOXYGEN=OFF','-DCMAKE_INSTALL_PREFIX='+str(p)])
        run([cmake,'--build',out,'-j',str(jobs)]);run([cmroot/'cmake/data/bin/ctest','--test-dir',out,'--output-on-failure'])
        run([cmake,'--install',out]);run([cmake,'--install',out/'zycore'])
        copy_notices(src,p,'Zydis');copy_notices(zycore,p,'Zycore')
        run(['gcc','-std=c11','-O2','-I'+str(p/'include'),recipe/'native_probe.c',p/'lib/libZydis.a',p/'lib/libZycore.a','-o',p/'bin/cpg-zydis-probe'])
    else:raise ValueError('unknown resource')
    print(json.dumps({'status':'passed','resource':a.resource,'prefix':str(p),'offline_build':True}))
if __name__=='__main__':main()
