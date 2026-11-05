#!/usr/bin/env python3
"""Build the complete locked LIKWID CPU profile with explicit relative launchers."""
from __future__ import annotations
import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from private_debs import extract,sha

def need(v,m):
    if not v: raise RuntimeError(m)

def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('source','build','prefix'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--jobs',type=int,required=True);a=p.parse_args();need(1<=a.jobs<=2,'Use one or two jobs')
    source,build,prefix=a.source.resolve(),a.build.resolve(),a.prefix.resolve()
    recipe=Path(__file__).resolve().parent;config=json.loads((recipe/'config.json').read_text())
    share=prefix/'share/likwid';proof=prefix/'share/compiler-playground/likwid';logs=build/'build-evidence'
    for d in (share,proof,logs,prefix/'libexec',prefix/'bin'):d.mkdir(parents=True,exist_ok=True)
    runtime=share/'runtime';closure=extract(recipe,config['recipe_inputs'],runtime,share/'inputs',logs/'decode',config['archival_only_links'])
    write(proof/'private-deb-closure.json',closure)
    guard=proof/'perl-guard';guard.mkdir();(guard/'CPGPrivateINC.pm').write_text('package CPGPrivateINC;\nBEGIN { @INC = split(/:/, $ENV{CPG_PRIVATE_PERL_LIBS}); }\n1;\n')
    common='#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
    perl=common+'runtime="$root/share/likwid/runtime"\nunset LD_PRELOAD LD_LIBRARY_PATH PERLLIB\nCPG_PRIVATE_PERL_LIBS="$runtime/usr/share/perl/5.38.2:$runtime/usr/lib/x86_64-linux-gnu/perl/5.38.2:$runtime/usr/lib/x86_64-linux-gnu/perl-base"\nPERL5LIB="$root/share/compiler-playground/likwid/perl-guard:$CPG_PRIVATE_PERL_LIBS"\nPERL5OPT=-MCPGPrivateINC\nexport CPG_PRIVATE_PERL_LIBS PERL5LIB PERL5OPT\nexec "$runtime/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$runtime/usr/lib/x86_64-linux-gnu" "$runtime/usr/bin/perl" -MCPGPrivateINC "$@"\n'
    (prefix/'libexec/cpg-perl').write_text(perl);(prefix/'libexec/cpg-perl').chmod(0o755)
    toolbin=build/'private-toolbin';toolbin.mkdir();(toolbin/'perl').write_text('#!/bin/sh\nexec '+shlex_quote(str(prefix/'libexec/cpg-perl'))+' "$@"\n');(toolbin/'perl').chmod(0o755)
    env=dict(os.environ,PATH=str(toolbin)+':/usr/bin:/bin',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
    for k in ('PERL5LIB','PERL5OPT','PERLLIB','LD_PRELOAD','LD_LIBRARY_PATH'):env.pop(k,None)
    work=build/'native-source-copy';shutil.copytree(source,work,symlinks=True)
    changes=[]
    header='''#ifndef CPG_LIKWID_RELOCATION_H
#define CPG_LIKWID_RELOCATION_H
#include <dlfcn.h>
#include <limits.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
extern int topology_init(void);
static char *cpg_likwid_path(const char *suffix) {
    static __thread char buffer[PATH_MAX];
    Dl_info info;
    if (!dladdr((void *)topology_init, &info) || !info.dli_fname || !realpath(info.dli_fname, buffer)) abort();
    char *end=strrchr(buffer, '/'); if (!end) abort(); *end='\\0';
    end=strrchr(buffer, '/'); if (!end) abort(); *end='\\0';
    size_t used=strlen(buffer); if (used+strlen(suffix)+2>sizeof(buffer)) abort();
    buffer[used++]='/'; strcpy(buffer+used,suffix); return buffer;
}
#endif
'''
    (work/'src/includes/cpg_relocation.h').write_text(header)
    for name in ('configuration.c','access_client.c','frequency_cpu.c'):
        f=work/'src'/name;old=f.read_text();new='#ifndef _GNU_SOURCE\n#define _GNU_SOURCE\n#endif\n#include "cpg_relocation.h"\n'+old
        for token,path in [('GROUPPATH','share/likwid/perfgroups'),('ACCESSDAEMON','sbin/likwid-accessD'),('FREQDAEMON','sbin/likwid-setFreq')]:new=new.replace('TOSTRING('+token+')','cpg_likwid_path("'+path+'")')
        f.write_text(new);changes.append({'path':'src/'+name,'before_sha256':hashlib.sha256(old.encode()).hexdigest(),'after_sha256':sha(f)})
        (logs/(name+'.patch')).write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='original/src/'+name,tofile='build/src/'+name)))
    write(logs/'source-copy-patches.json',{'modified_build_copy_only':True,'changes':changes,'added_header_sha256':sha(work/'src/includes/cpg_relocation.h')})
    shutil.copy2(work/'src/includes/cpg_relocation.h',proof/'cpg_relocation.h')
    commands=[]
    def run(label,argv,timeout=1500,cwd=work):
        started=dt.datetime.now(dt.timezone.utc);argv=list(map(str,argv));print(label,flush=True)
        with (logs/(label+'.stdout')).open('wb') as out,(logs/(label+'.stderr')).open('wb') as err:
            r=subprocess.run(argv,cwd=cwd,env=env,stdout=out,stderr=err,timeout=timeout,stdin=subprocess.DEVNULL)
        commands.append({'label':label,'argv':argv,'cwd':str(cwd),'returncode':r.returncode,'started_utc':started.isoformat(),'finished_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'stdout':label+'.stdout','stderr':label+'.stderr'})
        write(logs/'commands.json',commands);need(r.returncode==0,'Build command failed: '+label);return (logs/(label+'.stdout')).read_text(errors='replace')
    perl_observed=json.loads(run('private-perl-modules',[prefix/'libexec/cpg-perl','-MConfig','-MTime::HiRes','-Mthreads','-MThread::Queue','-MGetopt::Long','-MJSON::PP','-e','print JSON::PP->new->canonical->encode({version=>"$^V",modules=>\\%INC}),"\\n"']))
    need(perl_observed['version']=='v5.38.2','Wrong private Perl')
    for name,path in perl_observed['modules'].items():need(Path(path).resolve().is_relative_to(prefix),'Host Perl module loaded: '+name)
    options=['PREFIX='+str(prefix),'INSTALLED_PREFIX=/__CPG_LIKWID_PREFIX__','COMPILER=GCC','ACCESSMODE=accessdaemon','BUILDDAEMON=true','BUILD_SYSFEATURES=true','NVIDIA_INTERFACE=false','ROCM_INTERFACE=false','PWD='+str(work)]
    run('make',['make','-C',work,'-j'+str(a.jobs),*options])
    run('install',['make','-C',work,*options,'install','INSTALL_CHOWN=','-o','install_daemon','-o','install_freq'])
    for name in ('likwid-accessD','likwid-setFreq'):run('retain-'+name,['install','-D','-m','755',work/name,prefix/'sbin'/name])
    native=prefix/'libexec/native';native.mkdir();scripts=prefix/'libexec/upstream';scripts.mkdir()
    dispatch='''local root=assert(os.getenv("CPG_LIKWID_PREFIX"))
local function read_code(path)
  local file=assert(io.open(path,"r")); local code=file:read("*a"); file:close()
  code=code:gsub("^#![^\\n]*", "")
  return code:gsub("/__CPG_LIKWID_PREFIX__",function() return root end)
end
package.preload["likwid"]=function()
  return assert(load(read_code(root.."/share/lua/likwid.lua"),"@"..root.."/share/lua/likwid.lua"))()
end
local path=arg[1]; table.remove(arg,1); arg[0]=path
assert(load(read_code(path),"@"..path))()
'''
    (prefix/'libexec/dispatch.lua').write_text(dispatch)
    launch=common+'unset LD_PRELOAD\nLD_LIBRARY_PATH="$root/lib"\nCPG_LIKWID_PREFIX="$root"\nexport LD_LIBRARY_PATH CPG_LIKWID_PREFIX\n'
    generated=[]
    for directory in ('bin','sbin'):
        for f in sorted((prefix/directory).iterdir()):
            if f.is_symlink():continue
            data=f.read_bytes();generated.append({'path':str(f.relative_to(prefix)),'sha256':sha(f),'bytes':len(data)})
            if data.startswith(b'\x7fELF'):
                shutil.move(f,native/f.name);f.write_text(launch+'exec "$root/libexec/native/'+f.name+'" "$@"\n')
            elif b'likwid-lua' in data.split(b'\n',1)[0]:
                shutil.move(f,scripts/(f.name+'.lua'));f.write_text(launch+'exec "$root/libexec/native/likwid-lua" "$root/libexec/dispatch.lua" "$root/libexec/upstream/'+f.name+'.lua" "$@"\n')
            elif f.name=='feedGnuplot':
                shutil.move(f,scripts/f.name);f.write_text(common+'exec "$root/libexec/cpg-perl" "$root/libexec/upstream/feedGnuplot" "$@"\n')
            f.chmod(0o755)
    run('compile-public-api',['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(prefix/'include'),recipe/'api-check.c','-L'+str(prefix/'lib'),'-Wl,-rpath,$ORIGIN/../lib','-llikwid','-ldl','-o',prefix/'bin/likwid-api-check'])
    shutil.copy2(recipe/'api-check.c',proof/'api-check.c');shutil.copy2(recipe/'check.py',proof/'check.py')
    for f in (prefix/'lib/pkgconfig').glob('*.pc'):
        text=f.read_text().replace('/__CPG_LIKWID_PREFIX__','${pcfiledir}/../..');f.write_text(text)
    shutil.copytree(source,share/'source',symlinks=True)
    run('selected-upstream-topology',['python3',recipe/'upstream_tests.py','--prefix',prefix,'--output',logs/'upstream-topology'])
    shutil.copytree(logs/'upstream-topology',proof/'upstream-topology')
    for f in logs.iterdir():
        if f.is_file():shutil.copy2(f,proof/f.name)
    for name in ('config.json','build.py','runtime_check.py','private_debs.py'):shutil.copy2(recipe/name,proof/name)
    profile={'schema_version':1,'resource_id':'likwid','configuration':config['configuration'],'original_source_lock':config['original_source_lock'],'recipe_inputs':config['recipe_inputs'],'original_dependencies':config['original_dependencies'],'private_runtime':{'perl':perl_observed,'closure':closure},'native_machine_code_compilation':True,'original_source_tree_modified':False,'build_copy_patches':changes,'generated_upstream_files':generated,'unperformed':config['unperformed'],'system_package_transactions':'not_run','upstream_tests':json.loads((logs/'upstream-topology/summary.json').read_text()),'relocation_scope':'Relative LIKWID launchers and library-resolved default helper/group paths on declared Linux amd64 ABI.'}
    write(proof/'profile.json',profile)
    print(json.dumps({'status':'passed','native_machine_code_compilation':True,'private_perl_inputs':len(config['recipe_inputs'])}))

def shlex_quote(s):
    import shlex
    return shlex.quote(s)

if __name__=='__main__':main()
