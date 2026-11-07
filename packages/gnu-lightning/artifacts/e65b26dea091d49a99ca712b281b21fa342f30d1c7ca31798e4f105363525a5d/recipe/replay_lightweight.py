#!/usr/bin/env python3
"""Rebuild and verify six bounded x86-64 JIT capabilities without network access.

Every run must use a new output directory. Source, build and installation trees
are regular independent copies. Downloading is a separate maintainer operation.
"""
import argparse, concurrent.futures, hashlib, json, os, pathlib, platform, re
import shutil, subprocess, tarfile, time, zipfile
from runtime_layout import prepare_prefix

HERE=pathlib.Path(__file__).resolve().parent

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def validate_inputs(root,required):
    lock=json.loads((root/'inputs.lock.json').read_text())
    rows=lock.get('inputs')
    if lock.get('schema_version')!=1 or not isinstance(rows,list):raise ValueError('Unsupported input lock schema')
    by_name={}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('name'),str):raise ValueError('Invalid input row')
        name=row['name']
        if name in by_name:raise ValueError('Duplicate locked name: '+name)
        by_name[name]=row
    expected={name:'raw/'+name+'.tar.gz' for name in ['asmjit','xbyak','sljit','lightning','tinycc','luajit']}
    expected['libluajit-frozen-dev']='raw/libluajit-frozen-dev.deb'
    expected['cmake']='raw/cmake-3.31.6-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl'
    resolved={}
    for name in sorted(required):
        if name not in by_name:raise ValueError('Missing required input: '+name)
        row=by_name[name]
        if row.get('status')!='downloaded':raise ValueError('Required input is not acquired: '+name)
        if row.get('path')!=expected[name]:raise ValueError('Unexpected input path: '+name)
        digest=row.get('sha256');size=row.get('bytes')
        if not isinstance(digest,str) or re.fullmatch('[0-9a-f]{64}',digest) is None:raise ValueError('Invalid input digest: '+name)
        if type(size) is not int or size<=0:raise ValueError('Invalid input size: '+name)
        path=root/row['path']
        if path.is_symlink() or not path.is_file():raise ValueError('Input must be a regular file: '+name)
        if path.stat().st_size!=size or sha(path)!=digest:raise ValueError('Input mismatch: '+name)
        resolved[name]=path
    return resolved

def extract(archive,destination):
    destination.mkdir(parents=True)
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            p=pathlib.PurePosixPath(m.name)
            if p.is_absolute() or '..' in p.parts: raise ValueError(m.name)
            m.name=str(pathlib.PurePosixPath(*p.parts[1:]))
            if m.name!='.': t.extract(m,destination,filter='data')

def worker(name,output,cmake):
    src=output/'source'/name; build=output/'build'/name
    prefix=output/'install'/name; logs=output/'logs'/name
    build.mkdir(parents=True); prefix.mkdir(parents=True);logs.mkdir(parents=True)
    commands=[]; checks=[]
    env=dict(os.environ)
    env.update(LC_ALL='C',LANG='C',PYTHONDONTWRITEBYTECODE='1',CPG_OFFLINE='1')
    def run(args,label,cwd=build,expect=None):
        argv=[str(x) for x in args]
        started=time.monotonic()
        p=subprocess.run(argv,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=900)
        (logs/(label+'.log')).write_text(p.stdout)
        row={'label':label,'argv':argv,'cwd':str(cwd),'exit_code':p.returncode,'elapsed_seconds':round(time.monotonic()-started,6),'log':str((logs/(label+'.log')).relative_to(output))}
        commands.append(row)
        (logs/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if p.returncode:raise RuntimeError(f'{name}/{label}: exit {p.returncode}; {p.stdout[-2000:]}')
        if expect is not None:
            if expect not in p.stdout:raise RuntimeError(f'{name}/{label}: missing output {expect!r}')
            checks.append({'name':label,'expected':expect,'matched':True})
        return p.stdout
    try:
        extract(HERE/'raw'/(name+'.tar.gz'),src)
        (prefix/'bin').mkdir();(prefix/'lib').mkdir();(prefix/'include').mkdir()
        if name=='asmjit':
            run([cmake,'-S',src,'-B',build,'-DCMAKE_BUILD_TYPE=Release','-DASMJIT_STATIC=ON','-DASMJIT_TEST=OFF',f'-DCMAKE_INSTALL_PREFIX={prefix}'],'configure')
            run([cmake,'--build',build,'--parallel','2'],'build')
            run([cmake,'--install',build],'install')
            run(['g++','-std=c++20','-O2','-DASMJIT_STATIC','-I'+str(prefix/'include'),HERE/'fixtures/asmjit_check.cpp',prefix/'lib/libasmjit.a','-lpthread','-ldl','-o',prefix/'bin/cpg-asmjit-check'],'compile-check')
            run([prefix/'bin/cpg-asmjit-check'],'execute-check',expect='ASMJIT_PASS')
        elif name=='xbyak':
            shutil.copytree(src/'xbyak',prefix/'include/xbyak')
            run(['g++','-std=c++20','-O2','-I'+str(prefix/'include'),HERE/'fixtures/xbyak_check.cpp','-o',prefix/'bin/cpg-xbyak-check'],'compile-check')
            run([prefix/'bin/cpg-xbyak-check'],'execute-check',expect='XBYAK_PASS')
        elif name=='sljit':
            buildsrc=build/'checkout';shutil.copytree(src,buildsrc)
            run(['make','-j2','bin/first_program','bin/branch','bin/func_call'], 'build-examples',cwd=buildsrc)
            for example,expected in [('first_program','func return 15'),('branch','func return 6'),('func_call','func return 7')]:
                shutil.copy2(buildsrc/'bin'/example,prefix/'bin'/('sljit-'+example))
                run([prefix/'bin'/('sljit-'+example)],'execute-'+example,expect=expected)
            shutil.copytree(src/'sljit_src',prefix/'include/sljit-source')
            run(['ar','rcs',prefix/'lib/libsljit.a',buildsrc/'bin/sljitLir.o'],'static-library')
        elif name=='lightning':
            run([src/'configure',f'--prefix={prefix}','--disable-shared','--enable-static','--disable-disassembler'],'configure')
            run(['make','-j2'],'build')
            run(['make','install'],'install')
            run(['gcc','-O2','-I'+str(prefix/'include'),src/'doc/fact.c',prefix/'lib/liblightning.a','-lm','-o',prefix/'bin/cpg-lightning-factorial'],'compile-upstream-fact')
            for number,answer in [(0,1),(1,1),(5,120),(10,3628800)]:
                run([prefix/'bin/cpg-lightning-factorial',str(number)],'execute-fact-'+str(number),expect=f'factorial({number}) = {answer}')
        elif name=='tinycc':
            buildsrc=build/'checkout';shutil.copytree(src,buildsrc)
            run(['./configure',f'--prefix={prefix}'],'configure',cwd=buildsrc)
            run(['make','-j2'],'build',cwd=buildsrc)
            run(['make','install'],'install',cwd=buildsrc)
            run(['gcc','-O2','-I'+str(prefix/'include'),HERE/'fixtures/libtcc_check.c',prefix/'lib/libtcc.a','-ldl','-lm','-o',prefix/'bin/cpg-libtcc-check'],'compile-libtcc-check')
            run([prefix/'bin/cpg-libtcc-check',prefix/'lib/tcc'],'execute-libtcc-check',expect='LIBTCC_PASS')
            run([prefix/'bin/tcc','-B'+str(prefix/'lib/tcc'),HERE/'fixtures/tcc_elf_check.c','-o',prefix/'bin/cpg-tcc-elf-check'],'compile-c-to-elf')
            if (prefix/'bin/cpg-tcc-elf-check').read_bytes()[:4]!=b'\x7fELF':raise RuntimeError('TCC output is not ELF')
            run([prefix/'bin/cpg-tcc-elf-check'],'execute-elf-check',expect='TCC_ELF_PASS sum=499500')
        elif name=='luajit':
            buildsrc=build/'checkout';shutil.copytree(src,buildsrc)
            run(['make','-j2',f'PREFIX={prefix}'],'build',cwd=buildsrc)
            run(['make','install',f'PREFIX={prefix}'],'install',cwd=buildsrc)
            frozen=build/'frozen-deb';frozen.mkdir()
            run(['dpkg-deb','-x',HERE/'raw/libluajit-frozen-dev.deb',frozen],'extract-original-dev')
            run(['gcc','-O2','-I'+str(frozen/'usr/include/luajit-2.1'),HERE/'fixtures/luajit_driver.c',frozen/'usr/lib/x86_64-linux-gnu/libluajit-5.1.a','-Wl,-E','-lm','-ldl','-lpthread','-o',prefix/'bin/cpg-frozen-luajit-check'],'compile-original-apt-library')
            run([prefix/'bin/cpg-frozen-luajit-check',HERE/'fixtures/luajit_ffi_trace.lua'],'execute-original-apt-ffi-trace',expect='LUAJIT_TRACE_PASS')
            generated=build/'dynasm_check.c'
            run([buildsrc/'src/luajit',src/'dynasm/dynasm.lua','-o',generated,HERE/'fixtures/dynasm_check.dasc'],'dynasm-preprocess')
            run(['gcc','-O2','-DDASM_CHECKS','-I'+str(src/'dynasm'),generated,'-o',prefix/'bin/cpg-dynasm-check'],'compile-dynasm')
            run([prefix/'bin/cpg-dynasm-check'],'execute-dynasm',expect='DYNASM_PASS')
        docs=prefix/'share'/name;docs.mkdir(parents=True)
        for f in src.iterdir():
            if f.is_file() and (f.name.lower().startswith(('license','copying','copyright','readme'))):shutil.copy2(f,docs/f.name)
        # Preserve full source in a distinct regular-file installation subtree.
        shutil.copytree(src,docs/'source',symlinks=False)
        for f in HERE.joinpath('fixtures').iterdir():
            if f.is_file():
                fixtures=docs/'cpg-fixtures';fixtures.mkdir(exist_ok=True);shutil.copy2(f,fixtures/f.name)
        prepare_prefix(prefix,name,HERE)
        run(['python3',prefix/'run_checks.py'],'relocatable-profile',expect='"status": "passed"')
        files=[{'path':str(p.relative_to(prefix)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(prefix.rglob('*')) if p.is_file()]
        report={'name':name,'status':'passed','host':platform.platform(),'machine':platform.machine(),'scope':'bounded host x86_64 execution, not a cross-platform qualification','commands':commands,'checks':checks,'install_files':len(files),'install_bytes':sum(x['bytes'] for x in files),'file_inventory':files}
    except Exception as e:
        report={'name':name,'status':'failed','error':str(e),'commands':commands,'checks':checks}
    (logs/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['commands','file_inventory']}),flush=True)
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=pathlib.Path);parser.add_argument('--only',nargs='*',choices=['asmjit','xbyak','sljit','lightning','tinycc','luajit']);args=parser.parse_args()
    if platform.machine()!='x86_64':raise SystemExit('This execution profile explicitly requires x86_64 SysV Linux.')
    if args.output.exists():raise SystemExit('Output must be a fresh directory.')
    output=args.output.absolute();output.mkdir(parents=True)
    selected=args.only or ['asmjit','xbyak','sljit','lightning','tinycc','luajit']
    required=set(selected)
    if 'asmjit' in selected:required.add('cmake')
    if 'luajit' in selected:required.add('libluajit-frozen-dev')
    inputs=validate_inputs(HERE,required)
    cmake=None
    if 'cmake' in inputs:
        wheel=inputs['cmake']
        with zipfile.ZipFile(wheel) as z:z.extractall(output/'toolchain')
        for p in (output/'toolchain/cmake/data/bin').iterdir():p.chmod(0o755)
        cmake=output/'toolchain/cmake/data/bin/cmake'
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda n:worker(n,output,cmake),selected))
    report={'schema_version':1,'worker_id':'worker 016','network_used':False,'results':[{k:v for k,v in r.items() if k!='file_inventory'} for r in results],'all_passed':all(r['status']=='passed' for r in results)}
    (output/'replay-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['all_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
