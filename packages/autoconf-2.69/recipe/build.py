#!/usr/bin/env python3
"""Build original GNU Autotools into a private-runtime, relocatable script profile."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from private_debs import extract,sha

def need(value,message):
    if not value:raise RuntimeError(message)

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','build','prefix'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--jobs',type=int,required=True);p.add_argument('--autoconf-prefix',type=Path)
    args=p.parse_args();need(1<=args.jobs<=2,'Use at most two build jobs')
    recipe=Path(__file__).resolve().parent;config=json.loads((recipe/'config.json').read_text());name=config['id']
    source,build,prefix=args.source.resolve(),args.build.resolve(),args.prefix.resolve()
    share=prefix/'share'/name;proof=prefix/'share/compiler-playground'/name
    share.mkdir(parents=True);proof.mkdir(parents=True);(prefix/'libexec').mkdir();(prefix/'bin').mkdir()
    logs=build/'build-evidence';logs.mkdir(parents=True)
    private=share/'runtime'
    closure=extract(recipe,config['recipe_inputs'],private,share/'inputs',logs/'decode',config['archival_only_links'])
    write(proof/'private-deb-closure.json',closure)
    loader=private/'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
    library=private/'usr/lib/x86_64-linux-gnu'
    need(loader.is_file() and (private/'usr/bin/perl').is_file() and (private/'usr/bin/m4').is_file(),'Private runtime incomplete')
    guard=proof/'perl-guard';guard.mkdir()
    (guard/'CPGPrivateINC.pm').write_text('package CPGPrivateINC;\nBEGIN {\n @INC = split(/:/, $ENV{CPG_PRIVATE_PERL_LIBS});\n if ($ENV{CPG_AUTOMAKE_SHARE}) { @Automake::perl_libdirs = ($ENV{CPG_AUTOMAKE_SHARE}); @Aclocal::perl_libdirs = ($ENV{CPG_AUTOMAKE_SHARE}); }\n}\n1;\n')
    common='#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
    runtime=common+'runtime="$root/share/'+name+'/runtime"\nunset LD_PRELOAD LD_LIBRARY_PATH PERLLIB\n'
    libs='"$runtime/usr/share/perl/5.38.2:$runtime/usr/lib/x86_64-linux-gnu/perl/5.38.2:$runtime/usr/lib/x86_64-linux-gnu/perl-base"'
    perl=runtime+'CPG_PRIVATE_PERL_LIBS='+libs+'\nPERL5LIB="$root/share/compiler-playground/'+name+'/perl-guard:$CPG_PRIVATE_PERL_LIBS"\nPERL5OPT=-MCPGPrivateINC\nexport CPG_PRIVATE_PERL_LIBS PERL5LIB PERL5OPT\n'
    perl+='exec "$runtime/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$runtime/usr/lib/x86_64-linux-gnu" "$runtime/usr/bin/perl" -MCPGPrivateINC "$@"\n'
    m4=runtime+'exec "$runtime/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$runtime/usr/lib/x86_64-linux-gnu" "$runtime/usr/bin/m4" "$@"\n'
    for executable,body in [('cpg-perl',perl),('cpg-m4',m4)]:
        path=prefix/'libexec'/executable;path.write_text(body);path.chmod(0o755)
    work=build/'native-source-copy';shutil.copytree(source,work,symlinks=True)
    env=dict(os.environ,PATH='/usr/bin:/bin',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1',PERL=str(prefix/'libexec/cpg-perl'),M4=str(prefix/'libexec/cpg-m4'))
    for key in ('PERL5LIB','PERL5OPT','PERLLIB','LD_PRELOAD','LD_LIBRARY_PATH','AUTOM4TE','AC_MACRODIR','AUTOCONF','AUTOHEADER','ACLOCAL','AUTOMAKE','CPG_AUTOMAKE_SHARE'):
        env.pop(key,None)
    if args.autoconf_prefix:
        ac=args.autoconf_prefix.resolve();need((ac/'bin/autoconf').is_file(),'Autoconf dependency absent')
        env['PATH']=str(ac/'bin')+':/usr/bin:/bin';env['CPG_AUTOCONF_PREFIX']=str(ac)
        for tool in ('autoconf','autoheader','autom4te','autoreconf','autoupdate'):env[tool.upper()]=str(ac/'bin'/tool)
    commands=[]
    def command(label,argv,*,cwd=work,timeout=600):
        argv=list(map(str,argv));print(json.dumps({'label':label,'argv':argv}),flush=True)
        with (logs/(label+'.stdout')).open('wb') as out,(logs/(label+'.stderr')).open('wb') as err:
            result=subprocess.run(argv,cwd=cwd,env=env,stdout=out,stderr=err,stdin=subprocess.DEVNULL,timeout=timeout)
        commands.append({'label':label,'argv':argv,'cwd':str(cwd),'returncode':result.returncode,'stdout':label+'.stdout','stderr':label+'.stderr'})
        write(logs/'commands.json',commands);need(result.returncode==0,'Build command failed: '+label)
        return (logs/(label+'.stdout')).read_text(errors='replace')
    perl_version=command('private-perl-version',[prefix/'libexec/cpg-perl','-MConfig','-MJSON::PP','-e','print JSON::PP->new->canonical->encode({version=>"$^V",arch=>$Config{archname},inc=>\\%INC}),"\\n"'])
    observed=json.loads(perl_version);need(observed['version']=='v5.38.2','Unexpected private Perl version')
    for module,path in observed['inc'].items():need(Path(path).resolve().is_relative_to(prefix),'Perl loaded a host module: '+module)
    command('private-m4-version',[prefix/'libexec/cpg-m4','--version'])
    runtime_listing=command('private-perl-loader',[loader,'--library-path',library,'--list',private/'usr/bin/perl'])
    runtime_libraries=[]
    for line in runtime_listing.splitlines():
        match=re.search(r'=> (/\S+)\s+\(',line)
        if match:
            target=Path(match[1]).resolve();need(target.is_relative_to(private),'Host library escaped exact private closure')
            runtime_libraries.append({'path':target.relative_to(private).as_posix(),'sha256':sha(target)})
    need(runtime_libraries,'No private runtime libraries were observed')
    command('configure',[work/'configure','--prefix='+str(prefix)])
    command('make',['/usr/bin/make','-j'+str(args.jobs)])
    command('install',['/usr/bin/make','install'])
    upstream=prefix/'libexec/upstream';upstream.mkdir()
    generated=[]
    for path in sorted((prefix/'bin').iterdir()):
        if path.is_symlink():continue
        need(path.is_file(),'Unexpected generated bin member')
        generated.append({'path':path.name,'sha256':sha(path),'bytes':path.stat().st_size})
        shutil.move(path,upstream/path.name)
    aliases={p.name:os.readlink(p) for p in (prefix/'bin').iterdir() if p.is_symlink()}
    for alias in aliases:(prefix/'bin'/alias).unlink()
    is_automake=name.startswith('automake')
    if not is_automake:
        names=['autoconf','autoheader','autom4te','autoreconf','autoscan','autoupdate','ifnames']
        for tool in names:
            body=common+'AC_MACRODIR="$root/share/autoconf"\nautom4te_perllibdir="$AC_MACRODIR"\nAUTOM4TE_CFG="$AC_MACRODIR/autom4te.cfg"\nM4="$root/libexec/cpg-m4"\n'
            for key in ('autoconf','autoheader','autom4te','autoreconf','autoscan','autoupdate','ifnames'):body+=key.upper()+'="$root/bin/'+key+'"\n'
            body+='export AC_MACRODIR autom4te_perllibdir AUTOM4TE_CFG M4 AUTOCONF AUTOHEADER AUTOM4TE AUTORECONF AUTOSCAN AUTOUPDATE IFNAMES\n'
            interpreter='/bin/sh' if tool=='autoconf' else '"$root/libexec/cpg-perl"'
            options=' -B "$root/share/autoconf"' if tool=='autom4te' else ''
            body+='exec '+interpreter+' "$root/libexec/upstream/'+tool+'"'+options+' "$@"\n'
            (prefix/'bin'/tool).write_text(body);(prefix/'bin'/tool).chmod(0o755)
    else:
        (prefix/'share/aclocal').mkdir(exist_ok=True)
        for tool in ('automake','aclocal'):
            original=next((x['path'] for x in generated if x['path']==tool or x['path'].startswith(tool+'-')),None)
            need(original is not None,'Generated Automake entry missing')
            body=common+': "${CPG_AUTOCONF_PREFIX:?Set CPG_AUTOCONF_PREFIX to the managed autoconf-2.69 dependency prefix}"\n'
            body+='CPG_AUTOMAKE_SHARE="$root/share/automake-1.15"\nexport CPG_AUTOMAKE_SHARE\n'
            for key in ('autoconf','autoheader','autom4te','autoreconf','autoscan','autoupdate'):body+=key.upper()+'="$CPG_AUTOCONF_PREFIX/bin/'+key+'"\n'
            body+='AUTOMAKE="$root/bin/automake"\nACLOCAL="$root/bin/aclocal"\nexport AUTOCONF AUTOHEADER AUTOM4TE AUTORECONF AUTOSCAN AUTOUPDATE AUTOMAKE ACLOCAL\n'
            options=' --libdir="$root/share/automake-1.15"' if tool=='automake' else ' --automake-acdir="$root/share/aclocal-1.15" --system-acdir="$root/share/aclocal"'
            body+='exec "$root/libexec/cpg-perl" "$root/libexec/upstream/'+original+'"'+options+' "$@"\n'
            (prefix/'bin'/tool).write_text(body);(prefix/'bin'/tool).chmod(0o755)
            (prefix/'bin'/(tool+'-1.15')).symlink_to(tool)
    shutil.copytree(source,share/'source',symlinks=True)
    for name_ in ('COPYING','COPYINGv3','COPYING.EXCEPTION'):
        if (source/name_).is_file():shutil.copy2(source/name_,share/name_)
    for file in logs.glob('*.json'):shutil.copy2(file,proof/file.name)
    for file in logs.glob('*.stdout'):shutil.copy2(file,proof/file.name)
    for file in logs.glob('*.stderr'):shutil.copy2(file,proof/file.name)
    for filename in ('config.json','build.py','check.py','private_debs.py'):shutil.copy2(recipe/filename,proof/filename)
    profile={'schema_version':1,'resource_id':name,'configuration':config['configuration'],'original_source_lock':config['original_source_lock'],
       'recipe_inputs':config['recipe_inputs'],'original_dependencies':config['original_dependencies'],'private_runtime':{'libraries':runtime_libraries,'perl_modules':observed},
       'generated_upstream_scripts':generated,'original_generated_aliases':aliases,
       'runtime_projection':closure,'source_tree_modified':False,'source_generated_scripts':True,'native_machine_code_compilation':False,
       'upstream_tests':{'status':'not_run_in_build_phase','actual_installed_workflows':'See per-installation functional check receipts; further upstream test selection recorded separately.'},
       'unperformed':config['unperformed'],'relocation_scope':'Generated command-line scripts on Linux amd64 using installed private runtime; generated .pc/Makefile absolute build metadata is historical, not a public relocation contract.',
       'host_apt_transaction':'not_run'}
    write(proof/'profile.json',profile)
    print(json.dumps({'status':'passed','source_generated_tools':len(generated),'private_deb_inputs':len(config['recipe_inputs'])}))

if __name__=='__main__':main()
