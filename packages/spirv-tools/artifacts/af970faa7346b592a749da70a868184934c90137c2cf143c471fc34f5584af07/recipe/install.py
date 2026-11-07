#!/usr/bin/env python3
"""Rebuild the pinned upstream SPIRV-Tools source in a fresh offline tree."""
import argparse,hashlib,json,os,pathlib,shutil,subprocess,tarfile,zipfile

def require(ok,msg):
    if not ok:raise RuntimeError(msg)
def tree(archive,path):
    path.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as t:t.extractall(path,filter='data')
    dirs=[x for x in path.iterdir() if x.is_dir()];require(len(dirs)==1,'ambiguous source root')
    return dirs[0]
def main():
    p=argparse.ArgumentParser();p.add_argument('--assets',type=pathlib.Path,required=True);p.add_argument('--prefix',type=pathlib.Path,required=True)
    p.add_argument('--build',type=pathlib.Path,required=True);p.add_argument('--lock',type=pathlib.Path,required=True);p.add_argument('--jobs',type=int,default=2);a=p.parse_args()
    assets=a.assets.resolve();prefix=a.prefix.resolve();build=a.build.resolve();lock=json.loads(a.lock.read_text())
    for row in lock['inputs']:
        f=assets/row['material_path'];require(f.is_file() and f.stat().st_size==row['bytes'] and hashlib.sha256(f.read_bytes()).hexdigest()==row['sha256'],'locked input mismatch')
    src=tree(assets/'raw/spirv-tools.tar.gz',build/'source')
    hdr=tree(assets/'raw/spirv-headers.tar.gz',build/'headers')
    require(lock['headers_commit'] in (src/'DEPS').read_text(),'headers do not match upstream DEPS')
    for name in ('cmake','ninja'):
        archive=assets/lock[name+'_path'];out=build/'buildtools'/name;out.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                rel=pathlib.PurePosixPath(info.filename)
                require(not rel.is_absolute() and '..' not in rel.parts,'unsafe wheel path')
                z.extract(info,out)
                path=out/str(rel)
                if path.is_file():path.chmod((info.external_attr>>16)&0o777 or 0o644)
    cmake=build/'buildtools/cmake/cmake/data/bin/cmake'
    ninja=next((build/'buildtools/ninja').glob('*.data/scripts/ninja'));cmake.chmod(0o755);ninja.chmod(0o755)
    compile_root=build/'build'
    commands=[[str(cmake),'-S',str(src),'-B',str(compile_root),'-G','Ninja','-DCMAKE_MAKE_PROGRAM='+str(ninja),
               '-DSPIRV-Headers_SOURCE_DIR='+str(hdr),'-DSPIRV_SKIP_TESTS=ON','-DSPIRV_WERROR=OFF','-DCMAKE_BUILD_TYPE=Release',
               '-DCMAKE_CXX_FLAGS_RELEASE=-O1 -DNDEBUG -pipe','-DCMAKE_C_FLAGS_RELEASE=-O1 -DNDEBUG -pipe','-DCMAKE_INSTALL_PREFIX='+str(prefix)],
              [str(cmake),'--build',str(compile_root),'-j'+str(max(1,min(a.jobs,2)))],[str(cmake),'--install',str(compile_root)]]
    temporary=build/'tmp';temporary.mkdir(exist_ok=True);environment=dict(os.environ);environment['TMPDIR']=str(temporary)
    for argv in commands:print(json.dumps({'argv':argv}),flush=True);subprocess.run(argv,check=True,env=environment)
    (prefix/'sources').mkdir(exist_ok=True)
    for name in ('spirv-tools.tar.gz','spirv-headers.tar.gz'):shutil.copy2(assets/'raw'/name,prefix/'sources'/name)
    (prefix/'metadata').mkdir(exist_ok=True);shutil.copy2(a.lock,prefix/'metadata/build-lock.json')
    (prefix/'metadata/build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    for label,base in [('spirv-tools',src),('spirv-headers',hdr)]:
        to=prefix/'share/licenses'/label;to.mkdir(parents=True,exist_ok=True)
        for f in base.glob('LICENSE*'):
            if f.is_file():shutil.copy2(f,to/f.name)
        shutil.copy2(base/'README.md',to/'upstream-README.md')
    print(json.dumps({'status':'built','project':'SPIRV-Tools','commit':lock['source_commit'],'upstream_full_testsuite':'not_run','flags':'-O1 -DNDEBUG'}))
if __name__=='__main__':main()
