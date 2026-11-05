#!/usr/bin/env python3
"""Exercise private-runtime GNU Autotools on a real generated and compiled project."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

def need(value,message):
    if not value:raise RuntimeError(message)

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix',type=Path,required=True);p.add_argument('--build',type=Path,required=True);p.add_argument('--autoconf-prefix',type=Path)
    args=p.parse_args();prefix=args.prefix.resolve();recipe=Path(__file__).resolve().parent
    config=json.loads((recipe/'config.json').read_text());name=config['id'];is_automake=name.startswith('automake')
    args.build.mkdir(parents=True,exist_ok=True);work=Path(tempfile.mkdtemp(prefix='autotools-check-',dir=args.build))
    env=dict(os.environ,PATH=str(prefix/'bin')+':/usr/bin:/bin',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
    for key in ('PERL5LIB','PERL5OPT','PERLLIB','LD_PRELOAD','LD_LIBRARY_PATH','AUTOM4TE','AC_MACRODIR','AUTOCONF','AUTOHEADER','ACLOCAL','AUTOMAKE','CPG_AUTOMAKE_SHARE','CPG_AUTOCONF_PREFIX','MAKEFLAGS','MFLAGS'):
        env.pop(key,None)
    ac=prefix
    if is_automake:
        need(args.autoconf_prefix is not None,'Managed Autoconf dependency not supplied')
        ac=args.autoconf_prefix.resolve();need((ac/'bin/autoconf').is_file(),'Managed Autoconf dependency absent')
        env['CPG_AUTOCONF_PREFIX']=str(ac);env['PATH']=str(prefix/'bin')+':'+str(ac/'bin')+':/usr/bin:/bin'
    results=[]
    def run(label,argv,*,cwd=work,expected=0,contains=None,input_text=None):
        argv=list(map(str,argv));result=subprocess.run(argv,cwd=cwd,env=env,input=input_text,text=True,capture_output=True,timeout=120)
        (work/(label+'.stdout')).write_text(result.stdout);(work/(label+'.stderr')).write_text(result.stderr)
        row={'label':label,'argv':argv,'cwd':str(cwd),'returncode':result.returncode,'stdout':label+'.stdout','stderr':label+'.stderr','expected_returncode':expected}
        results.append(row);(work/'commands.json').write_text(json.dumps(results,indent=2)+'\n')
        need(result.returncode==expected,'Unexpected command status: '+label+'; '+result.stderr[-1200:])
        if contains is not None:need(contains in result.stdout+result.stderr,'Required oracle missing: '+label)
        return result.stdout
    version_tools=['autoconf','autoheader','autom4te','autoreconf','autoscan','autoupdate','ifnames'] if not is_automake else ['automake','aclocal','automake-1.15','aclocal-1.15']
    for tool in version_tools:run('version-'+tool,[prefix/'bin'/tool,'--version'],contains=config['version'])
    perl_program='use Config;use JSON::PP;use File::Spec;use File::Temp;open my $f,"<","/proc/self/maps" or die $!;local $/;my $maps=<$f>;print JSON::PP->new->canonical->encode({version=>"$^V",inc=>\\%INC,maps=>$maps}),"\\n";'
    observation=json.loads(run('private-perl-modules-and-maps',[prefix/'libexec/cpg-perl','-e',perl_program]))
    need(observation['version']=='v5.38.2','Wrong private interpreter version')
    for module,path in observation['inc'].items():need(Path(path).resolve().is_relative_to(prefix),'Host Perl module observed: '+module)
    actual_libraries=[]
    for line in observation['maps'].splitlines():
        if '/' in line:
            path=Path('/'+line.split('/',1)[1])
            if path.name.endswith('.so') or '.so.' in path.name or path.name in ('perl','perl5.38.2'):
                need(path.resolve().is_relative_to(prefix),'Host interpreter/library mapping observed: '+str(path));actual_libraries.append(str(path))
    need(actual_libraries,'No actual interpreter mappings observed')
    run('private-m4-functional',[prefix/'libexec/cpg-m4'],input_text="define(`square',`eval($1 * $1)')square(9)\n",contains='81')
    project=work/'positive';project.mkdir()
    (project/'configure.ac').write_text('AC_INIT([cpg-autotools-probe], [1.0])\nAC_CONFIG_SRCDIR([hello.c])\nAC_CONFIG_HEADERS([config.h])\n'+('AM_INIT_AUTOMAKE([foreign])\n' if is_automake else '')+'AC_PROG_CC\nAC_CHECK_HEADERS([stdio.h stdlib.h limits.h])\nAC_CHECK_FUNCS([malloc strchr])\nAC_DEFINE([CPG_SENTINEL], [37], [Exact generated configuration value])\nAC_CONFIG_FILES([Makefile])\nAC_OUTPUT\n')
    (project/'hello.c').write_text('#include "config.h"\n#include <stdio.h>\n#if !HAVE_STDIO_H || !HAVE_STDLIB_H || !HAVE_LIMITS_H || !HAVE_MALLOC || !HAVE_STRCHR || CPG_SENTINEL != 37\n#error invalid configuration\n#endif\nint main(void) { puts("CPG-GENERATED-CONFIG-37"); return 0; }\n')
    if is_automake:
        (project/'Makefile.am').write_text('bin_PROGRAMS = hello\nhello_SOURCES = hello.c\nTESTS = hello\n')
        run('aclocal-real-project',[prefix/'bin/aclocal'],cwd=project)
    else:
        (project/'Makefile.in').write_text('CC = @CC@\nCFLAGS = @CFLAGS@\nprefix = @prefix@\nall: hello\nhello: hello.c config.h\n\t$(CC) $(CFLAGS) -I. hello.c -o hello\ncheck: hello\n\t./hello\ninstall: hello\n\tmkdir -p $(DESTDIR)$(prefix)/bin\n\tcp hello $(DESTDIR)$(prefix)/bin/hello\n')
    run('autoheader-real-project',[ac/'bin/autoheader'],cwd=project)
    if is_automake:run('automake-real-project',[prefix/'bin/automake','--add-missing','--copy'],cwd=project)
    run('autoconf-real-project',[ac/'bin/autoconf'],cwd=project)
    run('configure-real-project',[project/'configure','--prefix=/cpg-generated-probe'],cwd=project)
    run('make-real-project',['/usr/bin/make','-j1'],cwd=project)
    run('execute-generated-project',[project/'hello'],cwd=project,contains='CPG-GENERATED-CONFIG-37')
    run('make-check-real-project',['/usr/bin/make','check'],cwd=project,contains='PASS: hello' if is_automake else 'CPG-GENERATED-CONFIG-37')
    destination=work/'staged-install';run('install-generated-project',['/usr/bin/make','install','DESTDIR='+str(destination)],cwd=project)
    run('execute-installed-project',[destination/'cpg-generated-probe/bin/hello'],contains='CPG-GENERATED-CONFIG-37')
    negative=work/'negative';negative.mkdir();(negative/'configure.ac').write_text('AC_INIT([negative], [1])\nAC_CPG_UNDEFINED_REQUIRED_MACRO\nAC_OUTPUT\n')
    run('reject-undefined-macro',[ac/'bin/autoconf'],cwd=negative,expected=1,contains='possibly undefined macro')
    if is_automake:
        bad=work/'negative-automake';bad.mkdir();(bad/'configure.ac').write_text('AC_INIT([bad], [1])\nAM_INIT_AUTOMAKE([foreign])\nAC_CONFIG_FILES([Makefile])\nAC_OUTPUT\n');(bad/'Makefile.am').write_text('bin_PROGRAMS = nonexistent\n')
        run('bad-project-aclocal',[prefix/'bin/aclocal'],cwd=bad)
        run('reject-missing-language-setup',[prefix/'bin/automake','--add-missing','--copy'],cwd=bad,expected=1,contains='CC')
    profile=json.loads((prefix/'share/compiler-playground'/name/'profile.json').read_text())
    need(len(profile['runtime_projection']['archival_only_links'])==2,'Projection exclusions differ')
    for row in config['recipe_inputs']:
        raw=prefix/'share'/name/'inputs'/Path(row['filename']).name
        need(raw.stat().st_size==row['bytes'] and sha(raw)==row['sha256'],'Original private DEB not retained')
    for relative in ('usr/share/doc/perl/copyright','usr/share/doc/m4/copyright','usr/share/doc/libc6/copyright'):
        need((prefix/'share'/name/'runtime'/relative).is_file(),'A required dependency license notice is absent')
    result={'schema_version':1,'resource_id':name,'status':'passed','real_commands':len(results),'negative_commands':1+int(is_automake),
        'commands':results,'private_perl_modules':observation['inc'],'private_runtime_mappings':actual_libraries,
        'original_private_archives':len(config['recipe_inputs']),'generated_program_stdout':'CPG-GENERATED-CONFIG-37',
        'omitted_link_runtime_scope':'The actual private interpreter/modules/m4, source generation and generated C program workflow all passed without either non-runtime projected link. No remote-tape or documentation-link behavior is claimed.',
        'source_build_classification':'source_built_interpreted_tool_with_private_runtime','official_benchmark':'not_run','full_gcc_regeneration':'not_run',
        'evidence_directory':str(work)}
    (work/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
