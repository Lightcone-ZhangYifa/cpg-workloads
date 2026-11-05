#!/usr/bin/env python3
"""Build OpenSSL from its fixed original source using an audited private Perl."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','build','prefix'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--jobs',type=int,required=True);args=parser.parse_args()
    if not 1<=args.jobs<=2:raise RuntimeError('This profile permits at most two compiler jobs')
    config=json.loads(Path(__file__).with_name('config.json').read_text())
    version=(args.source/'VERSION.dat').read_text()
    if not all(re.search(r'^'+k+'='+str(v)+r'$',version,re.M) for k,v in [('MAJOR',4),('MINOR',0),('PATCH',3)]):
        raise RuntimeError('Immutable OpenSSL source version mismatch')
    evidence=args.prefix/'share/compiler-playground/openssl';evidence.mkdir(parents=True)
    build=args.build/'openssl';build.mkdir()
    perl=Path(os.environ['CPG_PERL']).resolve(strict=True)
    environment=dict(os.environ,LC_ALL='C',CPG_PERL_ALLOWED_SOURCE=str(args.source.resolve()),
        CPG_PERL_ALLOWED_BUILD=str(build.resolve()),CC='/usr/bin/gcc',
        CPG_PERL_MODULE_PATH=os.environ['CPG_PERL_MODULE_PATH']+':'+str(args.source.resolve()/'util/perl')+':'+str(build.resolve()),
        CFLAGS='-O2 -march=x86-64 -mtune=generic',
        LDFLAGS="-Wl,-rpath,'$$ORIGIN:$$ORIGIN/..:$$ORIGIN/../lib'",
        HASHBANGPERL='/usr/bin/env perl',HARNESS_JOBS='1',HARNESS_VERBOSE='1',
        HARNESS_TAP_COPY=str(evidence/'upstream.tap'))
    for name in ('LD_LIBRARY_PATH','LD_PRELOAD','OPENSSL_CONF','OPENSSL_MODULES','OPENSSL_ENGINES'):
        environment.pop(name,None)
    commands=[]

    def run(label,argv,*,timeout=2400):
        command=[str(x) for x in argv]
        print(json.dumps({'label':label,'argv':command}),flush=True)
        with (evidence/(label+'.stdout')).open('wb') as out,(evidence/(label+'.stderr')).open('wb') as err:
            result=subprocess.run(command,cwd=build,env=environment,stdout=out,stderr=err,timeout=timeout)
        commands.append({'label':label,'argv':command,'returncode':result.returncode,
            'stdout':label+'.stdout','stderr':label+'.stderr'})
        (evidence/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if result.returncode:raise RuntimeError('OpenSSL upstream command failed: '+label)
        return (evidence/(label+'.stdout')).read_text(errors='replace')

    run('configure',[perl,args.source/'Configure','linux-x86_64','no-asm','shared',
        '--prefix='+str(args.prefix),'--openssldir='+str(args.prefix/'ssl'),'--libdir=lib'],timeout=180)
    makefile=(build/'Makefile').read_text()
    match=re.search(r'^PERL=(.+)$',makefile,re.M)
    if match is None or Path(match[1].strip()).resolve()!=perl:
        raise RuntimeError('Generated Makefile does not bind the exact private Perl interpreter')
    shutil.copy2(build/'configdata.pm',evidence/'configdata.pm')
    run('build',['/usr/bin/make','-C',build,'-j'+str(args.jobs),'build_inst_sw'])
    run('build-selected-tests',['/usr/bin/make','-C',build,'-j'+str(args.jobs),*config['upstream_targets']])
    listed=run('upstream-list',['/usr/bin/make','-C',build,'list-tests'],timeout=60)
    selected=[]
    for name in config['upstream_recipes']:
        matches=list((args.source/'test/recipes').glob('*-'+name+'.t'))
        if len(matches)!=1 or name not in listed:
            raise RuntimeError('Selected upstream recipe is absent from actual list: '+name)
        selected.append(matches[0].name)
    stdout=run('upstream-tests',['/usr/bin/make','-C',build,'run_tests','TESTS='+' '.join(config['upstream_recipes'])],timeout=900)
    stderr=(evidence/'upstream-tests.stderr').read_text(errors='replace')
    combined=stdout+'\n'+stderr
    summaries=list(re.finditer(r'Files=(\d+), Tests=(\d+)',combined))
    summary=summaries[-1] if summaries else None
    if summary is None or int(summary[1])!=len(selected) or int(summary[2])<len(selected) or 'Result: PASS' not in combined:
        raise RuntimeError('Selected upstream harness list did not execute completely')
    if (len(summaries)!=2 or int(summaries[0][1])!=1 or int(summaries[0][2])!=0 or
            '00-prep_fipsmodule_cnf.t' not in combined or
            'FIPS module config file only supported in a fips build' not in combined):
        raise RuntimeError('Mandatory no-FIPS preparation scope differs from this configured profile')
    for name in selected:
        if name not in combined:raise RuntimeError('Missing actual upstream recipe output: '+name)
    if re.search(r'^\s*not ok\b',combined,re.M):
        raise RuntimeError('An upstream assertion failed')
    tap=(evidence/'upstream.tap').read_text(errors='replace')
    top_level_ok=re.findall(r'^ok\b[^\n]*$',tap,re.M)
    if len(top_level_ok)!=int(summary[2]):
        raise RuntimeError('Raw TAP top-level results differ from the harness planned count')
    top_level_skipped=sum(bool(re.search(r'#\s*skip\b',line,re.I)) for line in top_level_ok)
    top_level_executed=int(summary[2])-top_level_skipped
    if top_level_executed<1:raise RuntimeError('Upstream suite executed no assertions')
    run('install',['/usr/bin/make','-C',build,'install_sw'],timeout=300)
    # Installed pkg-config metadata is relative to its independently selected prefix.
    for path in (args.prefix/'lib/pkgconfig').glob('*.pc'):
        content=path.read_text();expected='prefix='+str(args.prefix)
        if content.count(expected)!=1:raise RuntimeError('Unexpected installed pkg-config prefix')
        content=content.replace(str(args.prefix),'${prefix}')
        content=content.replace('prefix=${prefix}','prefix=${pcfiledir}/../..',1);path.write_text(content)
    elf=run('installed-cli-rpath',['/usr/bin/readelf','-d',args.prefix/'bin/openssl'],timeout=60)
    if '$ORIGIN/../lib' not in elf or str(build) in elf or str(args.prefix) in elf:
        raise RuntimeError('Installed ELF CLI does not have portable local runtime paths')
    audit=Path(environment['CPG_PERL_AUDIT_DIR']);private=Path(environment['CPG_PERL_PRIVATE_ROOT']).resolve()
    roots=[private,args.source.resolve(),build.resolve()];records=[];modules={};interpreters=set()
    for path in sorted(audit.glob('*.tsv')):
        rows=[]
        for line in path.read_text().splitlines():
            parts=line.split('\t');rows.append(parts)
            if parts[0]=='interpreter':
                interpreters.add(parts[1]);
                if Path(parts[1]).resolve()!=perl:raise RuntimeError('Audited subprocess used a different Perl')
            elif parts[0] in ('module','xs'):
                module=Path(parts[-1]).resolve(strict=True)
                if not any(module.is_relative_to(root) for root in roots):
                    raise RuntimeError('Audited module came from an undeclared host path')
                modules[str(module)]={'sha256':hashlib.sha256(module.read_bytes()).hexdigest(),
                    'scope':'private-deb' if module.is_relative_to(private) else 'original-or-generated-source'}
        records.append({'file':path.name,'rows':rows})
    if not records or not modules or interpreters!={str(perl)}:
        raise RuntimeError('Private Perl process/module execution evidence is empty')
    (evidence/'perl-execution-audit.json').write_text(json.dumps({'status':'passed','interpreter':str(perl),
        'process_count':len(records),'module_files':modules,'processes':records},indent=2)+'\n')
    shutil.copytree(args.source,args.prefix/'share/openssl/source',symlinks=True)
    for name in ('build.py','check.py','config.json','consumer.c'):
        shutil.copy2(Path(__file__).with_name(name),evidence/name)
    capabilities=[line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith(('Uid:','Gid:','CapEff:','NoNewPrivs:'))]
    profile={'schema_version':1,'id':'openssl','version':'4.0.3','source_modified':False,
        'configuration':'linux-x86_64, no-asm, shared and static libraries, default and legacy providers',
        'upstream_tests':{'selected_recipes':config['upstream_recipes'],'actual_recipe_files':selected,
            'compiled_targets':config['upstream_targets'],
            'mandatory_prep':{'recipe':'00-prep_fipsmodule_cnf.t','files':1,'tests':0,'status':'skipped','reason':'FIPS disabled in this explicit no-asm default/legacy profile'},
            'files':int(summary[1]),'top_level_planned':int(summary[2]),'top_level_skipped':top_level_skipped,
            'top_level_executed':top_level_executed,'result':'PASS','identity':capabilities,
            'scope':'Selected source-build upstream recipes only; nested assertions are not added to top-level counts'},
        'perl_execution':{'processes':len(records),'module_files':len(modules),'interpreter':str(perl)},
        'unperformed':config['unperformed']}
    (evidence/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')


if __name__=='__main__':main()
