#!/usr/bin/env python3
"""Build fixed Valgrind source with explicit private and host-debug closures."""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
from private_debs import extract,sha

def need(value,message):
    if not value:raise RuntimeError(message)
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def main():
    parser=argparse.ArgumentParser()
    for k in ('source','build','prefix'):parser.add_argument('--'+k,type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=2);a=parser.parse_args()
    need(1<=a.jobs<=2,'Use one or two build jobs')
    source,build,prefix=a.source.resolve(),a.build.resolve(),a.prefix.resolve()
    recipe=Path(__file__).resolve().parent;config=json.loads((recipe/'config.json').read_text())
    share=prefix/'share/valgrind';proof=prefix/'share/compiler-playground/valgrind'
    share.mkdir(parents=True);proof.mkdir(parents=True)
    (prefix/'bin').mkdir();(prefix/'libexec').mkdir()
    logs=build/'build-evidence';logs.mkdir(parents=True)
    runtime=share/'runtime'
    closure=extract(recipe,config['private_inputs'],runtime,share/'inputs',logs/'decode',config['archival_only_links'])
    for n in ('lib','lib64'):
        p=runtime/n
        if not p.exists():p.symlink_to('usr/'+n)
    compat=share/'compat-debug'
    extra=config['compat_debug_input']
    compat_closure=extract(recipe,[extra],compat,share/'compat-inputs',logs/'compat-decode',config['compat_archival_links'])
    library=runtime/'usr/lib/x86_64-linux-gnu';loader=library/'ld-linux-x86-64.so.2'
    gccdir=runtime/'usr/lib/gcc/x86_64-linux-gnu/13'
    env=dict(os.environ,PATH='/usr/bin:/bin',LC_ALL='C',DEBUGINFOD_URLS='',PYTHONDONTWRITEBYTECODE='1')
    for key in ('LD_PRELOAD','LD_LIBRARY_PATH','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','GCC_EXEC_PREFIX','COMPILER_PATH','LIBRARY_PATH','VALGRIND_LIB','VALGRIND_OPTS','PERL5LIB','PERL5OPT','PERLLIB'):env.pop(key,None)
    commands=[]
    def run(label,argv,*,cwd=build,timeout=600,expected=0,environment=None):
        argv=list(map(str,argv));start=time.perf_counter()
        with (logs/(label+'.stdout')).open('wb') as out,(logs/(label+'.stderr')).open('wb') as err:
            p=subprocess.run(argv,cwd=cwd,env=environment or env,stdout=out,stderr=err,timeout=timeout)
        row={'label':label,'argv':argv,'cwd':str(cwd),'returncode':p.returncode,'elapsed_seconds':time.perf_counter()-start,'stdout':label+'.stdout','stderr':label+'.stderr'}
        commands.append(row);write(logs/'commands.json',commands)
        if expected is not None:need(p.returncode==expected,'Command failed: '+label)
        return (logs/(label+'.stdout')).read_text(errors='replace'),(logs/(label+'.stderr')).read_text(errors='replace')
    pairs=[];debug_aliases=[]
    for label,binary,debugroot in [('private-loader',loader,runtime),('private-libc',library/'libc.so.6',runtime),('host-loader',Path('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'),compat),('host-libc',Path('/usr/lib/x86_64-linux-gnu/libc.so.6'),compat)]:
        text,_=run(label+'-build-id',['/usr/bin/readelf','-n',binary]);bid=re.search(r'Build ID:\s*([0-9a-f]+)',text).group(1)
        sym=debugroot/'usr/lib/debug/.build-id'/bid[:2]/(bid[2:]+'.debug')
        need(sym.is_file(),'No exact detached symbols for '+label)
        out,_=run(label+'-debug-build-id',['/usr/bin/readelf','-n',sym]);need(re.search(r'Build ID:\s*([0-9a-f]+)',out).group(1)==bid,'Detached Build-ID mismatch')
        out,_=run(label+'-debuglink',['/usr/bin/readelf','--string-dump=.gnu_debuglink',binary]);name=re.search(r'\[\s*0\]\s+(\S+)',out).group(1)
        if label.startswith('private'):
            aliases=[binary.parent/'.debug'/name]
        else:
            aliases=[compat/d/name for d in ('usr/lib/x86_64-linux-gnu','lib/x86_64-linux-gnu','lib64')]
        for alias in aliases:
            alias.parent.mkdir(parents=True,exist_ok=True);alias.symlink_to(os.path.relpath(sym,alias.parent))
            debug_aliases.append({'path':alias.relative_to(prefix).as_posix(),'target':os.readlink(alias),'sha256':sha(sym)})
        pairs.append({'label':label,'object':str(binary),'object_sha256':sha(binary),'build_id':bid,'debug_sha256':sha(sym),'debug_file':sym.relative_to(prefix).as_posix(),'input_version':'2.39-0ubuntu8.6' if label.startswith('host') else '2.39-0ubuntu8.9'})
    write(proof/'debug-pairing.json',{'status':'passed','objects':pairs,'aliases':debug_aliases,'mismatched_debug_allowed':False})
    tools=prefix/'libexec/valgrind-build-tools';tools.mkdir()
    common='#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)\nprivate="$root/share/valgrind/runtime"\nlibrary="$private/usr/lib/x86_64-linux-gnu"\ngccdir="$private/usr/lib/gcc/x86_64-linux-gnu/13"\nloader="$library/ld-linux-x86-64.so.2"\nunset LD_PRELOAD LD_LIBRARY_PATH GCC_EXEC_PREFIX COMPILER_PATH LIBRARY_PATH CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH\n'
    for name in ('as','ar','nm','objdump','readelf','strip','ranlib'):
        p=tools/name;p.write_text(common+'exec "$loader" --library-path "$library" "$private/usr/bin/x86_64-linux-gnu-'+name+'" "$@"\n');p.chmod(0o755)
    (tools/'ld').write_text(common+'exec "$loader" --library-path "$library" "$private/usr/bin/x86_64-linux-gnu-ld.bfd" --sysroot="$private" -L"$gccdir" -L"$library" "$@" --dynamic-linker "$loader" -rpath "$library"\n');(tools/'ld').chmod(0o755)
    (tools/'cc1').write_text(common+'exec "$loader" --library-path "$library" "$private/usr/libexec/gcc/x86_64-linux-gnu/13/cc1" "$@"\n');(tools/'cc1').chmod(0o755)
    includes=' -isystem "$gccdir/include" -isystem "$private/usr/include/x86_64-linux-gnu" -isystem "$private/usr/include" '
    driver=' --sysroot="$private" -B"$root/libexec/valgrind-build-tools/" -B"$gccdir/" -nostdinc '
    (tools/'cc').write_text(common+'exec /usr/bin/cc'+driver+includes+'"$@"\n');(tools/'cc').chmod(0o755)
    cxx=' -nostdinc++ -isystem "$private/usr/include/c++/13" -isystem "$private/usr/include/x86_64-linux-gnu/c++/13" -isystem "$private/usr/include/c++/13/backward" '
    (tools/'c++').write_text(common+'exec /usr/bin/c++'+driver+cxx+includes+'"$@"\n');(tools/'c++').chmod(0o755)
    guard=proof/'perl-guard';guard.mkdir()
    (guard/'CPGPrivateINC.pm').write_text('package CPGPrivateINC;\nBEGIN { @INC = split(/:/, $ENV{CPG_PRIVATE_PERL_LIBS}); }\n1;\n')
    perl='#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nruntime="$root/share/valgrind/runtime"\nunset LD_PRELOAD LD_LIBRARY_PATH PERLLIB\nCPG_PRIVATE_PERL_LIBS="$runtime/usr/share/perl/5.38.2:$runtime/usr/lib/x86_64-linux-gnu/perl/5.38.2:$runtime/usr/lib/x86_64-linux-gnu/perl-base"\nPERL5LIB="$root/share/compiler-playground/valgrind/perl-guard:$CPG_PRIVATE_PERL_LIBS"\nPERL5OPT=-MCPGPrivateINC\nexport CPG_PRIVATE_PERL_LIBS PERL5LIB PERL5OPT\nexec "$runtime/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$runtime/usr/lib/x86_64-linux-gnu" "$runtime/usr/bin/perl" -MCPGPrivateINC "$@"\n'
    (prefix/'libexec/cpg-valgrind-perl').write_text(perl);(prefix/'libexec/cpg-valgrind-perl').chmod(0o755)
    (tools/'perl').write_text(common+'exec "$root/libexec/cpg-valgrind-perl" "$@"\n');(tools/'perl').chmod(0o755)
    env.update(PATH=str(tools)+':/usr/bin:/bin',CC=str(tools/'cc'),CXX=str(tools/'c++'),CPP=str(tools/'cc')+' -E',CXXCPP=str(tools/'c++')+' -E',AR=str(tools/'ar'),LD=str(tools/'ld'),NM=str(tools/'nm'),RANLIB=str(tools/'ranlib'),PERL=str(prefix/'libexec/cpg-valgrind-perl'),CFLAGS='',CXXFLAGS='',TMPDIR=str(build/'temporary'))
    (build/'temporary').mkdir();write(logs/'build-environment.json',{k:env[k] for k in ('PATH','CC','CXX','CPP','CXXCPP','AR','LD','NM','RANLIB','PERL','CFLAGS','CXXFLAGS','TMPDIR')})
    native=build/'native-build';native.mkdir()
    run('configure',[source/'configure','--prefix='+str(prefix)],cwd=native)
    for n in ('config.log','config.status','config.h'):shutil.copy2(native/n,logs/n)
    header=build/'header-probe.c';header.write_text('#include <stdio.h>\n#include <stdint.h>\nint main(void){return 0;}\n')
    text,_=run('private-header-probe',[tools/'cc','-v','-H','-E',header]);paths=[m.group(1) for m in re.finditer(r'^#\s+\d+\s+"([^"]+)"',text,re.M) if m.group(1).startswith('/')]
    need(paths and all(Path(p).resolve().is_relative_to(runtime) or Path(p).resolve()==header for p in paths),'Unexpected host header')
    run('make',['/usr/bin/make','-j'+str(a.jobs)],cwd=native,timeout=900)
    run('install',['/usr/bin/make','install'],cwd=native,timeout=300)
    # Every installed ELF CLI executes via this installation's loader. The
    # original native bytes retain their recorded link metadata unchanged.
    saved=prefix/'libexec/valgrind-native';saved.mkdir();entries=[]
    for executable in sorted((prefix/'bin').iterdir()):
        need(executable.is_file() and not executable.is_symlink(),'Unexpected exported command member')
        data=executable.read_bytes();name=executable.name;shutil.move(executable,saved/name)
        body='#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nruntime="$root/share/valgrind/runtime"\nVALGRIND_LIB="$root/libexec/valgrind"\nexport VALGRIND_LIB\n'
        if data.startswith(b'\x7fELF'):
            body+='exec "$runtime/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$runtime/usr/lib/x86_64-linux-gnu" "$root/libexec/valgrind-native/'+name+'"'
            if name=='valgrind':body+=' --extra-debuginfo-path="$root/share/valgrind/compat-debug"'
            body+=' "$@"\n';kind='native_elf'
        elif b'perl' in data.split(b'\n',1)[0]:
            body+='exec "$root/libexec/cpg-valgrind-perl" "$root/libexec/valgrind-native/'+name+'" "$@"\n';kind='upstream_perl_script'
        elif b'python3' in data.split(b'\n',1)[0]:
            body+='exec /usr/bin/python3 -I "$root/libexec/valgrind-native/'+name+'" "$@"\n';kind='upstream_python_script'
        elif b'sh' in data.split(b'\n',1)[0]:
            body+='exec /bin/sh "$root/libexec/valgrind-native/'+name+'" "$@"\n';kind='upstream_shell_script'
        else:raise RuntimeError('Unreviewed original command interpreter: '+name)
        executable.write_text(body);executable.chmod(0o755);entries.append({'name':name,'original_sha256':hashlib.sha256(data).hexdigest(),'kind':kind})
    run('original-smoke',[prefix/'bin/valgrind','--tool=memcheck','--error-exitcode=97','/bin/true'],cwd=prefix)
    selected=config['selected_upstream_cases']
    run('build-selected-upstream',['/usr/bin/make','-C',native/'memcheck/tests','-j'+str(a.jobs),*selected],cwd=native,timeout=600)
    # Automake VPATH builds generate programs and configured filters in native,
    # but this upstream harness resolves .vgtest/expected fixtures from cwd.
    # Copy only absent original support members into this private build tree;
    # never alter the source or overwrite generated filters/programs.
    fixture_copies=[]
    for subtree in ('tests','memcheck/tests'):
        for original in sorted((source/subtree).rglob('*')):
            relative=original.relative_to(source);destination=native/relative
            if destination.exists() or destination.is_symlink():continue
            if original.is_symlink():
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.symlink_to(os.readlink(original))
                fixture_copies.append({'path':relative.as_posix(),'kind':'symlink','target':os.readlink(original)})
            elif original.is_file():
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,destination)
                need(sha(original)==sha(destination),'Original upstream fixture changed')
                fixture_copies.append({'path':relative.as_posix(),'kind':'file','sha256':sha(original)})
            elif original.is_dir():destination.mkdir(parents=True,exist_ok=True)
    write(logs/'original-upstream-fixture-projection.json',{'status':'passed','source_modified':False,'existing_build_members_overwritten':False,'copied_members':fixture_copies})
    # The original unmodified harness and expected output files are used.
    # It is a declared selection, not a claim that make regtest ran in full.
    out,err=run('upstream-regression-selection',[prefix/'libexec/cpg-valgrind-perl',native/'tests/vg_regtest','--valgrind='+str(prefix/'bin/valgrind'),'--valgrind-lib='+str(prefix/'libexec/valgrind'),*['memcheck/tests/'+n for n in selected]],cwd=native,timeout=600,expected=None)
    case_logs=logs/'upstream-selected';case_logs.mkdir()
    for n in selected:
        for result in sorted((native/'memcheck/tests').glob(n+'.*')):
            if result.is_file() and result.name.endswith(('.out','.diff','.trs','.log')):
                shutil.copy2(result,case_logs/result.name)
    fixture_locks=[]
    for n in selected:
        for fixture in sorted((source/'memcheck/tests').glob(n+'.*')):
            if fixture.is_file() and any(token in fixture.name for token in ('.vgtest','.exp')):
                fixture_locks.append({'path':fixture.relative_to(source).as_posix(),'sha256':sha(fixture)})
    write(case_logs/'fixture-locks.json',{'original_fixtures_unchanged':True,'original_members':fixture_locks,'configured_original_harness_sha256':sha(native/'tests/vg_regtest'),'user_CFLAGS':'','user_CXXFLAGS':'','flag_policy':'Use unchanged upstream configure/Makefile selection; no global user optimization override for regression programs.'})
    need(commands[-1]['returncode']==0,'Original upstream selected cases failed')
    count=re.search(r'== (\d+) tests, 0 stderr failures, 0 stdout failures, 0 stderrB failures, 0 stdoutB failures, 0 post failures ==',out)
    need(count and int(count.group(1))==len(selected) and '***' not in out and 'skipping' not in out.lower(),'Unexpected upstream failure/skip or missing execution count')
    cases=[]
    for n in selected:
        result=(native/'memcheck/tests'/(n+'.vgtest.trs')).read_text()
        need(':test-result: PASS' in result,'Original harness did not record PASS: '+n)
        cases.append({'test':'memcheck/tests/'+n,'result':'PASS'})
    upstream={'status':'passed','selected_cases':selected,'cases':cases,'executed':len(selected),'failed':0,'skipped':0,'original_full_suite_command':config['original_upstream_commands'],'full_suite_executed':False,'harness':'unmodified tests/vg_regtest; complete stdout/stderr retained'}
    shutil.copytree(source,share/'source',symlinks=True)
    for n in ('COPYING','COPYING.DOCS'):shutil.copy2(source/n,share/n)
    shutil.copytree(logs,proof/'build-evidence',symlinks=True)
    for n in ('config.json','build.py','check.py','private_debs.py'):shutil.copy2(recipe/n,proof/n)
    write(proof/'profile.json',{'schema_version':1,'status':'passed','resource_id':'valgrind','configuration':config['configuration'],'original_source_lock':config['original_source_lock'],'recipe_inputs':config['recipe_inputs'],'original_dependencies':config['original_dependencies'],'runtime_projection':closure,'compatibility_projection':compat_closure,'debug_pairs':pairs,'source_tree_modified':False,'native_machine_code_compilation':True,'exported_commands':entries,'upstream_tests':upstream,'target_runtime_scope':'Ubuntu24.04 x86_64; original host2.39-0ubuntu8.6 loader/libc with exact added debug, plus private2.39-0ubuntu8.9 compiled clients. These are separate observations.','host_apt_transaction':'not_run','unperformed':config['unperformed']})
    print(json.dumps({'status':'passed','resource':'valgrind','original_smoke':'passed','upstream_selected':len(selected),'source_modified':False}))
if __name__=='__main__':main()
