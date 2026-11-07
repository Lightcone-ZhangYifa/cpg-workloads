#!/usr/bin/env python3
"""Offline bounded upstream translator build, linking the fixed LLVM18 shared SDK."""
import argparse, hashlib, json, os, pathlib, re, shutil, subprocess, tarfile

def require(ok,msg):
    if not ok:raise RuntimeError(msg)

def extract_tar(archive, root):
    root.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as t:t.extractall(root,filter='data')
    dirs=[p for p in root.iterdir() if p.is_dir()]
    require(len(dirs)==1,'Expected one upstream source root')
    return dirs[0]

def extract_deb(archive, root, headers_only=False):
    root.mkdir(parents=True,exist_ok=True)
    # dpkg-deb only unpacks a selected local archive; no package manager or scripts run.
    p=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(archive)],stdout=subprocess.PIPE)
    keep_bin={'clang','llvm-dis','opt','llvm-config'}
    with tarfile.open(fileobj=p.stdout,mode='r|') as t:
        for m in t:
            name=m.name.removeprefix('./')
            if headers_only:
                selected=name.startswith(('usr/include/llvm-18/','usr/include/llvm-c-18/','usr/lib/llvm-18/include/','usr/share/doc/llvm-18-dev/'))
            else:
                selected=name.startswith(('usr/lib/llvm-18/lib/','usr/lib/x86_64-linux-gnu/','usr/lib/clang/18/','usr/share/doc/'))
                if name.startswith('usr/lib/llvm-18/bin/'):
                    selected=pathlib.PurePosixPath(name).name in keep_bin
                if name.startswith('usr/lib/llvm-18/include/'):
                    selected=True
            if selected:t.extract(m,root,filter='data')
    require(p.wait()==0,'dpkg-deb extraction failed')

def make_wrappers(prefix):
    (prefix/'bin').mkdir(exist_ok=True)
    for name,rel in {'clang-18':'sdk/usr/lib/llvm-18/bin/clang','llvm-spirv':'native/bin/llvm-spirv',
                     'llvm-dis':'sdk/usr/lib/llvm-18/bin/llvm-dis','opt':'sdk/usr/lib/llvm-18/bin/opt'}.items():
        p=prefix/'bin'/name
        p.write_text('#!/usr/bin/env python3\nimport os,pathlib,sys\np=pathlib.Path(__file__).resolve().parents[1]\ne=dict(os.environ)\ne["LD_LIBRARY_PATH"]=str(p/"native/lib")+os.pathsep+str(p/"sdk/usr/lib/x86_64-linux-gnu")+os.pathsep+str(p/"sdk/usr/lib/llvm-18/lib")+(os.pathsep+e["LD_LIBRARY_PATH"] if e.get("LD_LIBRARY_PATH") else "")\nx=p/'+repr(rel)+'\nos.execve(x,[str(x),*sys.argv[1:]],e)\n')
        p.chmod(0o755)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--assets',type=pathlib.Path,required=True)
    ap.add_argument('--prefix',type=pathlib.Path,required=True);ap.add_argument('--build',type=pathlib.Path,required=True)
    ap.add_argument('--lock',type=pathlib.Path,required=True);a=ap.parse_args()
    assets=a.assets.resolve();prefix=a.prefix.resolve();build=a.build.resolve();lock=json.loads(a.lock.read_text())
    for r in lock['inputs']:
        p=assets/r['material_path'];require(p.is_file() and p.stat().st_size==r['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],'input identity mismatch: '+str(p))
    src=extract_tar(assets/lock['source_path'],build/'translator-source')
    hdr=extract_tar(assets/lock['headers_path'],build/'spirv-headers')
    sdk=prefix/'sdk'
    for r in lock['inputs']:
        if r.get('sdk_role')=='runtime':extract_deb(assets/r['material_path'],sdk)
        elif r.get('sdk_role')=='headers':extract_deb(assets/r['material_path'],build/'llvm-dev',True)
    omitted=[]
    optional_links={'usr/share/doc/llvm-18/changelog.Debian.gz':'../llvm-18-runtime/changelog.Debian.gz',
                    'usr/lib/clang/18/lib':'../../llvm-18/lib/clang/18/lib'}
    for path,target in optional_links.items():
        f=sdk/path
        if f.is_symlink() and not f.exists():
            require(str(f.readlink())==target,'unexpected optional SDK link target')
            omitted.append({'path':path,'target':target,'reason':'unselected optional Debian changelog or sanitizer runtime; OpenCL compile and translation do not consume it'})
            f.unlink()
    for f in sdk.rglob('*'):
        if f.is_symlink():require(not f.readlink().is_absolute() and f.exists(),'unresolved or absolute runtime SDK link: '+str(f))
    upstream=(src/'lib/SPIRV/CMakeLists.txt').read_text()
    block=re.search(r'set\(SRC_LIST\s+(.*?)\n\)',upstream,re.S)
    require(block is not None,'upstream source-list declaration missing')
    names=block[1].split()
    require(names==lock['upstream_source_list'],'upstream source list differs from reviewed fixed list')
    flags=['-std=c++17','-stdlib=libstdc++','-fPIC','-O0','-g0','-pipe','-DNDEBUG','-fno-exceptions','-funwind-tables','-D_GNU_SOURCE','-D__STDC_CONSTANT_MACROS','-D__STDC_FORMAT_MACROS','-D__STDC_LIMIT_MACROS']
    includes=[build/'llvm-dev/usr/include/llvm-18',build/'llvm-dev/usr/include/llvm-c-18',src/'include',hdr/'include',src/'lib/SPIRV',src/'lib/SPIRV/libSPIRV',src/'lib/SPIRV/Mangler']
    flags += ['-I'+str(x) for x in includes]
    (build/'objects').mkdir(exist_ok=True);(prefix/'native/lib').mkdir(parents=True,exist_ok=True);(prefix/'native/bin').mkdir(parents=True,exist_ok=True)
    commands=[]
    temporary=build/'tmp';temporary.mkdir(exist_ok=True)
    environment=dict(os.environ);environment['TMPDIR']=str(temporary)
    environment['LD_LIBRARY_PATH']=str(sdk/'usr/lib/x86_64-linux-gnu')+':'+str(sdk/'usr/lib/llvm-18/lib')
    compiler=[str(sdk/'usr/lib/llvm-18/bin/clang'),'--driver-mode=g++']
    def run(argv):
        print(json.dumps({'argv':[str(x) for x in argv]}),flush=True)
        commands.append([str(x) for x in argv]);subprocess.run(argv,check=True,env=environment)
    objects=[]
    for index,name in enumerate(names):
        obj=build/'objects'/('%02d.o'%index);objects.append(obj)
        run([*compiler,*flags,'-c',str(src/'lib/SPIRV'/name),'-o',str(obj)])
    llvm=sdk/'usr/lib/llvm-18/lib/libLLVM.so.1'
    require(llvm.is_file(),'fixed libLLVM shared dependency absent')
    lib=prefix/'native/lib/libLLVMSPIRVLib.so.18.1'
    run([*compiler,'-shared','-Wl,-soname,libLLVMSPIRVLib.so.18.1','-o',str(lib),*[str(x) for x in objects],str(llvm)])
    run([*compiler,*flags,str(src/'tools/llvm-spirv/llvm-spirv.cpp'),str(lib),str(llvm),'-Wl,-rpath,$ORIGIN/../lib','-o',str(prefix/'native/bin/llvm-spirv')])
    make_wrappers(prefix)
    (prefix/'sources').mkdir(exist_ok=True)
    shutil.copy2(assets/lock['source_path'],prefix/'sources'/pathlib.Path(lock['source_path']).name)
    shutil.copy2(assets/lock['headers_path'],prefix/'sources'/pathlib.Path(lock['headers_path']).name)
    (prefix/'metadata').mkdir(exist_ok=True)
    shutil.copy2(a.lock,prefix/'metadata/build-lock.json')
    (prefix/'metadata/build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    (prefix/'metadata/omitted-sdk-links.json').write_text(json.dumps(omitted,indent=2)+'\n')
    licenses=prefix/'share/licenses/spirv-llvm-translator';licenses.mkdir(parents=True,exist_ok=True)
    for base,pattern,label in [(src,'LICENSE*','translator'),(hdr,'LICENSE*','spirv-headers')]:
        for p in base.glob(pattern):
            if p.is_file():shutil.copy2(p,licenses/(label+'-'+p.name))
    shutil.copy2(src/'README.md',licenses/'upstream-README.md')
    print(json.dumps({'status':'built','source_files':len(names),'compiler':'bundled Clang18.1.3 C++ driver','mode':'O0-g0','link':'fixed LLVM18 shared library','upstream_full_testsuite':'not_run'}))

if __name__=='__main__':main()
