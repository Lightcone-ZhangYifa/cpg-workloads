"""Original CPG source-package hook: local, explicit, offline construction."""
import argparse, ctypes, hashlib, json, os, pathlib, platform, shutil, subprocess, sys, tarfile, zipfile

def require(value, message):
    if not value:
        raise RuntimeError(message)

def main():
    ap=argparse.ArgumentParser()
    for x in ('prefix','build','assets','recipe'):ap.add_argument('--'+x,required=True)
    a=ap.parse_args();p=pathlib.Path(a.prefix);b=pathlib.Path(a.build);assets=pathlib.Path(a.assets);recipe=pathlib.Path(a.recipe)
    cfg=json.loads((recipe/'profile.json').read_text());name=cfg['id']
    require(sys.version_info[:2]==(3,12),'This exact wheel profile requires CPython 3.12')
    require(platform.system()=='Linux' and platform.machine() in ('x86_64','AMD64'),'This profile requires Linux x86_64')
    logs=b/'build-logs';logs.mkdir(exist_ok=True)
    env=os.environ.copy();env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PIP_NO_CACHE_DIR='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_NO_INDEX='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    env.pop('PYTHONPATH',None)
    commands=[]
    def run(argv,label,cwd=b,extra=None):
        argv=list(map(str,argv));e=env.copy();e.update(extra or {})
        with (logs/(label+'.stdout')).open('w') as out,(logs/(label+'.stderr')).open('w') as err:
            q=subprocess.run(argv,cwd=cwd,env=e,stdout=out,stderr=err,timeout=1800)
        commands.append({'label':label,'argv':argv,'returncode':q.returncode})
        (logs/'commands.json').write_text(json.dumps(commands,indent=2))
        require(q.returncode==0,label+' failed; see '+str(logs))
    for component,row in cfg['components'].items():
        src=assets/row['material_path'];dest=b/'source'/component;dest.mkdir(parents=True,exist_ok=True)
        with tarfile.open(src) as archive:
            for member in archive.getmembers():
                bits=pathlib.PurePosixPath(member.name).parts[1:]
                if not bits:continue
                rel=pathlib.PurePosixPath(*bits)
                if row.get('select') and not any(str(rel)==x or str(rel).startswith(x+'/') for x in row['select']):continue
                member.name=str(rel)
                archive.extract(member,dest,filter='data')
    (p/'samples').mkdir(exist_ok=True)
    shutil.copytree(recipe/'samples',p/'samples',dirs_exist_ok=True)
    (p/'build').mkdir(exist_ok=True)
    shutil.copytree(b/'source',p/'source',symlinks=False)
    shutil.copy2(recipe/'profile.json',p/'profile.json')
    shutil.copy2(recipe/'check.py',p/'check.py')
    shutil.copy2(recipe/'install.py',p/'install.py')
    # Exact, independent wheel environments. Pip is the real wheel installer.
    if cfg.get('wheels'):
        run([sys.executable,'-S','-m','venv','--copies',p/'venv'],'create-venv')
        python=p/'venv/bin/python'
        wheels=[assets/x['material_path'] for x in cfg['wheels']]
        if cfg.get('build_wheels'):
            run([python,'-m','pip','install','--no-index','--no-deps','--no-compile',*[assets/x['material_path'] for x in cfg['build_wheels']]],'python-build-dependencies')
            output=b/'built-wheels';output.mkdir()
            run([python,'-m','pip','wheel','--no-index','--no-deps','--no-build-isolation','--wheel-dir',output,b/'source'/name],'python-source-wheel')
            generated=list(output.glob('*.whl'))
            require(len(generated)==1,'Expected one wheel built from the locked upstream source')
            wheels=[x for x in wheels if x.name!=cfg['local_main_wheel']]+generated
        run([python,'-m','pip','install','--no-index','--no-deps','--no-compile',*wheels],'offline-pip-install')
        run([python,'-m','pip','check'],'pip-check')
        if name=='gptune':
            (p/'venv/lib/python3.12/site-packages/GPy/installation.cfg').write_text('[plotting]\nlibrary = none\n')
    if name in ('cppatf','pyatf','gptune'):
        run(['gcc','-O3','-fPIC','-shared',p/'samples/cpu_kernel.c','-o',p/'build/libcpg_kernel.so'],'cpu-kernel')
    if name=='cppatf':
        run(['g++','-std=c++17','-O0','-include','cstring','-I'+str(b/'source/cppatf'),'-I'+str(b/'source/cppatf/include'),p/'samples/cppatf_check.cpp','-L'+str(p/'build'),'-lcpg_kernel','-Wl,-rpath,$ORIGIN','-o',p/'build/cppatf-check'],'cppatf-harness')
    if name in ('cltune','ktt'):
        ctypes.CDLL('libOpenCL.so.1')
        ctypes.CDLL('libstdc++.so.6')
        native=p/'native-opencl';native.mkdir()
        for row in cfg['native_wheels']:
            with zipfile.ZipFile(assets/row['material_path']) as archive:archive.extractall(native)
        cmake_root=b/'cmake';cmake_root.mkdir()
        with zipfile.ZipFile(assets/cfg['cmake']['material_path']) as archive:archive.extractall(cmake_root)
        cmake=cmake_root/'cmake/data/bin/cmake';cmake.chmod(0o755)
        for exe in (cmake.parent).iterdir():
            if exe.is_file():exe.chmod(0o755)
        if name=='cltune':
            ob=b/'objects'
            run([cmake,'-S',b/'source/cltune','-B',ob,'-DCMAKE_POLICY_VERSION_MINIMUM=3.5','-DSAMPLES=OFF','-DTESTS=OFF','-DUSE_OPENCL=ON','-DBUILD_SHARED_LIBS=ON','-DOPENCL_INCLUDE_DIRS='+str(b/'source/opencl-headers'),'-DOPENCL_LIBRARIES=/usr/lib/x86_64-linux-gnu/libOpenCL.so.1'],'configure-cltune')
            run([cmake,'--build',ob,'--parallel','1'],'build-cltune')
            (p/'build/cltune').mkdir()
            for f in ob.glob('libcltune.so*'):
                if f.is_file():shutil.copy2(f,p/'build/cltune'/f.name)
            run(['g++','-std=c++11','-O1','-DUSE_OPENCL','-I'+str(b/'source/cltune/include'),p/'samples/cltune_check.cpp','-L'+str(p/'build/cltune'),'-lcltune','-Wl,-rpath,$ORIGIN/cltune','-o',p/'build/cltune-check'],'cltune-harness')
        else:
            cm='''cmake_minimum_required(VERSION 3.16)
project(CpgKtt CXX)
set(CMAKE_CXX_STANDARD 17)
file(GLOB_RECURSE KTT_SOURCES "${KTT_ROOT}/Source/*.cpp")
add_library(ktt SHARED ${KTT_SOURCES} "${KTT_ROOT}/Libraries/pugixml-1.11.4/pugixml.cpp" "${KTT_ROOT}/Libraries/CTPL-Ahajha/ctpl_stl.cpp")
target_include_directories(ktt PUBLIC "${KTT_ROOT}/Source" "${OCL_HEADERS}" "${KTT_ROOT}/Libraries/CTPL-Ahajha" "${KTT_ROOT}/Libraries/date-3" "${KTT_ROOT}/Libraries/Json-3.9.1" "${KTT_ROOT}/Libraries/pugixml-1.11.4")
target_compile_definitions(ktt PRIVATE KTT_LIBRARY KTT_API_OPENCL CL_TARGET_OPENCL_VERSION=300)
target_compile_options(ktt PRIVATE -O1)
target_link_libraries(ktt PRIVATE /usr/lib/x86_64-linux-gnu/libOpenCL.so.1 pthread dl)
add_executable(ktt-check "${HARNESS}")
target_link_libraries(ktt-check PRIVATE ktt)
set_target_properties(ktt-check PROPERTIES BUILD_RPATH "$ORIGIN")
'''
            project=b/'project';project.mkdir();(project/'CMakeLists.txt').write_text(cm)
            ob=b/'objects'
            run([cmake,'-S',project,'-B',ob,'-DKTT_ROOT='+str(b/'source/ktt'),'-DOCL_HEADERS='+str(b/'source/opencl-headers'),'-DHARNESS='+str(p/'samples/ktt_check.cpp')],'configure-ktt')
            run([cmake,'--build',ob,'--parallel','1'],'build-ktt')
            for f in ('libktt.so','ktt-check'):shutil.copy2(ob/f,p/'build'/f)
    (p/'build-provenance.json').write_text(json.dumps({'id':name,'offline':True,'host':{'python':sys.version,'platform':platform.platform()},'commands':commands,'profile_sha256':hashlib.sha256((recipe/'profile.json').read_bytes()).hexdigest(),'source_material':'Full original archives remain in the CPG source package; execution subtrees are copied independently.'},indent=2))
    print(json.dumps({'status':'installed','id':name,'prefix':str(p),'offline':True}))

if __name__=='__main__':main()
