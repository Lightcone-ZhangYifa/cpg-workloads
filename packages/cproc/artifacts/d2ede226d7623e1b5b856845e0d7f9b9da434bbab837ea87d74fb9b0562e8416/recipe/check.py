#!/usr/bin/env python3
"""Exercise cproc's complete installed native pipeline with fixed private inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import traceback

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def need(value,message):
    if not value:raise RuntimeError(message)

def write(path,value):path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

PROGRAM=r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <gnu/libc-version.h>
static uint64_t kernel(uint64_t x) {
    unsigned i; uint64_t a[17];
    for (i=0;i<17;++i) a[i]=(uint64_t)i*31337+11;
    for (i=0;i<1000;++i) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        x += a[i%17];
    }
    return x;
}
int main(void) {
    FILE *maps; char line[4096];
    printf("oracle=%llu\n",(unsigned long long)kernel(UINT64_C(0x123456789abcdef0)));
    printf("libc=%s\n",gnu_get_libc_version());
    maps=fopen("/proc/self/maps","r");
    if (!maps) return 9;
    while (fgets(line,sizeof(line),maps))
        if (strstr(line,"libc.so") || strstr(line,"ld-linux")) printf("map=%s",line);
    if (fclose(maps)) return 10;
    return 0;
}
'''

def oracle():
    mask=(1<<64)-1;x=0x123456789abcdef0
    for i in range(1000):
        x=(x^((x<<13)&mask))&mask;x^=x>>7;x=(x^((x<<17)&mask))&mask
        x=(x+(i%17)*31337+11)&mask
    return x

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('prefix','build','qbe-prefix'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    prefix=args.prefix.resolve();qbe=args.qbe_prefix.resolve();args.build.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='cproc-functional-',dir=args.build))
    summary={'status':'running','prefix':str(prefix),'qbe_prefix':str(qbe),'work':str(work),'commands':[]}
    private=prefix/'share/cproc/toolchain';library=private/'usr/lib/x86_64-linux-gnu';tools=prefix/'libexec/cproc-tools'
    env=dict(os.environ);env.update(PATH=str(tools)+':/usr/bin:/bin',CPG_QBE_PREFIX=str(qbe),TMPDIR=str(work))
    for key in ('LD_LIBRARY_PATH','LD_PRELOAD','GCC_EXEC_PREFIX','COMPILER_PATH','LIBRARY_PATH','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH'):env.pop(key,None)
    def run(label,argv,expected=0):
        argv=[str(x) for x in argv]
        p=subprocess.run(argv,cwd=work,env=env,capture_output=True,timeout=120)
        (work/(label+'.stdout')).write_bytes(p.stdout);(work/(label+'.stderr')).write_bytes(p.stderr)
        summary['commands'].append({'label':label,'argv':argv,'cwd':str(work),'returncode':p.returncode,'expected':'nonzero' if expected=='nonzero' else expected,'stdout':label+'.stdout','stderr':label+'.stderr'})
        write(work/'checks.json',summary)
        need(p.returncode!=0 if expected=='nonzero' else p.returncode==expected,'Unexpected command result: '+label)
        return p.stdout.decode(errors='replace'),p.stderr.decode(errors='replace')
    try:
        profile=json.loads((prefix/'share/compiler-playground/cproc/profile.json').read_text())
        need(sha(qbe/'bin/qbe')==profile['qbe_dependency_executable_sha256'],'Resolved QBE executable differs from the locked qualified binary dependency')
        summary['qbe_binding']={'expected_artifact_sha256':profile['qbe_dependency_artifact_sha256'],'executable_sha256':sha(qbe/'bin/qbe'),'prefix':str(qbe),'binding':'independently managed exact binary dependency'}
        raw=[]
        for row in profile['recipe_inputs']:
            path=prefix/'share/cproc/inputs'/Path(row['filename']).name
            need(path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],'Changed private original input '+row['id'])
            raw.append({'id':row['id'],'sha256':row['sha256'],'bytes':row['bytes']})
        summary['private_original_inputs']={'status':'passed','count':len(raw),'inputs':raw}
        output,_=run('target',[prefix/'bin/cproc','-dumpmachine'])
        need(output.strip()=='x86_64-linux-gnu','Wrong compiler target')
        for name,binary in [('assembler','cpg-as'),('linker','cpg-ld'),('preprocessor','cpg-cpp')]:
            out,err=run(name+'-version',[tools/binary,'--version'])
            need(('2.42' in out) if name!='preprocessor' else ('13.3.0' in out),'Wrong private tool version '+name)
        loader=library/'ld-linux-x86-64.so.2'
        for name,binary in [('as',private/'usr/bin/x86_64-linux-gnu-as'),('ld',private/'usr/bin/x86_64-linux-gnu-ld.bfd'),('cpp',private/'usr/bin/x86_64-linux-gnu-cpp-13'),('cc1',private/'usr/libexec/gcc/x86_64-linux-gnu/13/cc1')]:
            out,_=run('private-library-origins-'+name,[loader,'--library-path',library,'--list',binary])
            resolved=[line.split('=>',1)[1].split('(',1)[0].strip() for line in out.splitlines() if '=>' in line]
            need(resolved and all(Path(x).resolve().is_relative_to(private) for x in resolved),'Private tool resolves a shared library outside its exact prefix: '+name)
        for name in ('cproc','cproc-qbe'):
            out,_=run('native-static-'+name,['/usr/bin/readelf','-l',prefix/'libexec/cproc-native'/name])
            need('INTERP' not in out,'Installed native compiler is not static')
        (work/'program.c').write_text(PROGRAM)
        cc=prefix/'bin/cproc'
        run('preprocess',[cc,'-v','-std=c11','-E','program.c','-o','program.i'])
        preprocessed=(work/'program.i').read_text()
        headerpaths=[m.group(1) for m in re.finditer(r'^#\s+\d+\s+"([^"]+)"',preprocessed,re.M) if m.group(1).startswith('/')]
        need(headerpaths and all(Path(x).resolve().is_relative_to(private) for x in headerpaths),'Preprocessing opened an undeclared host header')
        summary['preprocessing_headers']={'status':'passed','all_absolute_header_paths_private':True,'paths':sorted(set(headerpaths))}
        run('frontend-qbe',[cc,'-v','-emit-qbe','program.i','-o','program.qbe'])
        need(re.search(r'export\s+function\s+w\s+\$main\(', (work/'program.qbe').read_text()),'Missing real emitted QBE main function')
        run('backend-assembly',[cc,'-v','-S','program.qbe','-o','program.s'])
        need((work/'program.s').stat().st_size>0,'Empty QBE assembly')
        run('assemble-object',[cc,'-v','-c','program.s','-o','program.o'])
        need((work/'program.o').read_bytes()[:4]==b'\x7fELF','Assembler did not produce ELF')
        linkout,linkerr=run('link-native',[cc,'-v','-Wl,-t','program.o','-o','program'])
        trace=linkout+'\n'+linkerr
        for name in ('crt1.o','crti.o','crtbegin.o','crtend.o','crtn.o'):
            locations=[line.strip() for line in linkout.splitlines() if line.strip().endswith('/'+name)]
            need(locations and all(Path(x).resolve().is_relative_to(private) for x in locations),'A linked startup object is not private: '+name)
        output,_=run('execute-native',[work/'program'])
        need('oracle='+str(oracle())+'\n' in output,'Compiled integer behavior differs from independent Python oracle')
        need('libc=2.39\n' in output,'Compiled program used unexpected glibc version')
        mapped=[line.rsplit(None,1)[-1] for line in output.splitlines() if line.startswith('map=')]
        need(mapped and any(x.endswith('/libc.so.6') for x in mapped) and any(x.endswith('/ld-linux-x86-64.so.2') for x in mapped),'Missing live process library evidence')
        need(all(Path(x).resolve().is_relative_to(private) for x in mapped),'Generated program loaded host libc or dynamic loader')
        summary['native_pipeline']={'status':'passed','stages':['preprocess','cproc frontend','QBE 1.3 backend','private as','private ld','execute'],'integer_oracle':oracle(),'live_runtime_mappings':sorted(set(mapped))}
        run('direct-source-compile',[cc,'-v','-std=c11','program.c','-o','direct'])
        direct,_=run('direct-source-execute',[work/'direct'])
        need('oracle='+str(oracle())+'\n' in direct,'Direct compile/execute changed behavior')
        (work/'invalid.c').write_text('int main(void) { return not_declared_here + ; }\n')
        _,err=run('reject-invalid-c',[cc,'invalid.c','-o','must-not-exist'],expected='nonzero')
        need(bool(err.strip()) and not (work/'must-not-exist').exists(),'Malformed C did not fail safely')
        (work/'undefined.c').write_text('extern int unavailable_symbol(void); int main(void) { return unavailable_symbol(); }\n')
        _,err=run('reject-undefined-link',[cc,'undefined.c','-o','must-not-link'],expected='nonzero')
        need('unavailable_symbol' in err and not (work/'must-not-link').exists(),'Undefined symbol did not fail at link time')
        for name in ('stage1','stage2'):
            need(profile['upstream_tests'][name]['executed']>0 and profile['upstream_tests'][name]['failed']==0 and profile['upstream_tests'][name]['skipped']==0,'No executed upstream suite proof')
        summary.update(status='passed',negative_cases=2,upstream_tests=profile['upstream_tests'])
    except Exception as error:
        summary.update(status='failed',error=repr(error),traceback=traceback.format_exc())
        raise
    finally:
        write(work/'checks.json',summary)
        print(json.dumps({'status':summary['status'],'work':str(work),'integer_oracle':summary.get('native_pipeline',{}).get('integer_oracle')}))

if __name__=='__main__':main()
