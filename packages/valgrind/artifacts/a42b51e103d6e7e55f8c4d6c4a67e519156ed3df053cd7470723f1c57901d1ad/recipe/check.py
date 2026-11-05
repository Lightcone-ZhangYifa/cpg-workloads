#!/usr/bin/env python3
"""Exercise each independent prefix without substituting the original client."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,tempfile
from pathlib import Path
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(value,message):
    if not value:raise RuntimeError(message)
def main():
    p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);p.add_argument('--build',type=Path,required=True);a=p.parse_args()
    prefix=a.prefix.resolve();a.build.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='valgrind-functional-',dir=a.build));logs=root/'logs';logs.mkdir()
    profile=json.loads((prefix/'share/compiler-playground/valgrind/profile.json').read_text())
    env=dict(os.environ,LC_ALL='C',DEBUGINFOD_URLS='',PATH=str(prefix/'bin')+':/usr/bin:/bin')
    for key in ('VALGRIND_OPTS','VALGRIND_LIB','VALGRIND_LIB_INNER','LD_PRELOAD','LD_LIBRARY_PATH','PERL5LIB','PERL5OPT','PERLLIB'):env.pop(key,None)
    commands=[]
    def run(label,argv,expected=0,timeout=120):
        argv=list(map(str,argv))
        with (logs/(label+'.stdout')).open('wb') as out,(logs/(label+'.stderr')).open('wb') as err:
            result=subprocess.run(argv,cwd=root,env=env,stdout=out,stderr=err,timeout=timeout)
        commands.append({'label':label,'argv':argv,'returncode':result.returncode,'expected':expected})
        (root/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        need(result.returncode==expected,'Unexpected '+label+' return code')
        return (logs/(label+'.stdout')).read_text(errors='replace'),(logs/(label+'.stderr')).read_text(errors='replace')
    fingerprints=[]
    for pair in profile['debug_pairs']:
        current=Path(pair['object']) if pair['label'].startswith('host-') else prefix/'share/valgrind/runtime/usr/lib/x86_64-linux-gnu'/Path(pair['object']).name
        need(sha(current)==pair['object_sha256'],'Unsupported runtime object; current bytes differ from the precisely qualified '+pair['label'])
        out,_=run('runtime-fingerprint-'+pair['label'],['/usr/bin/readelf','-n',current])
        build_id=re.search(r'Build ID:\s*([0-9a-f]+)',out).group(1)
        need(build_id==pair['build_id'],'Runtime Build-ID differs from exact detached symbols')
        fingerprints.append({'label':pair['label'],'actual_object':str(current),'sha256':sha(current),'build_id':build_id,'version':pair['input_version']})
    out,_=run('original-client-interpreter',['/usr/bin/readelf','-l','/bin/true'])
    interpreter=re.search(r'Requesting program interpreter: ([^\]]+)',out).group(1)
    need(Path(interpreter).resolve()==Path('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2').resolve(),'Unexpected original client PT_INTERP')
    vg=prefix/'bin/valgrind'
    out,err=run('version',[vg,'--version']);need(out.strip()=='valgrind-3.27.1','Unexpected Valgrind version')
    # This is exactly the preexisting resource command, not an alternate ld.so invocation.
    out,err=run('original-declared-smoke',[vg,'--tool=memcheck','--error-exitcode=97','/bin/true'])
    need('ERROR SUMMARY: 0 errors' in err,'Original smoke lacked clean Memcheck accounting')
    positives='#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\nint main(int argc,char **argv){char *p=malloc(64);if(!p)return 2;strcpy(p,"valgrind-r05-ok");puts(p);free(p);return argc==2?atoi(argv[1]):0;}\n'
    negative='#include <stdlib.h>\nint main(void){volatile unsigned char *p=malloc(4);if(!p)return 2;p[4]=42;free((void*)p);return 0;}\n'
    for name,body in [('positive',positives),('negative',negative)]:
        (root/(name+'.c')).write_text(body)
        for kind,cc in [('host','/usr/bin/cc'),('private',str(prefix/'libexec/valgrind-build-tools/cc'))]:
            run('compile-'+kind+'-'+name,[cc,'-O0','-g',root/(name+'.c'),'-o',root/(kind+'-'+name)])
    observations={}
    for kind in ('host','private'):
        out,err=run(kind+'-positive',[vg,'--tool=memcheck','--leak-check=full','--error-exitcode=97',root/(kind+'-positive')])
        need(out.strip()=='valgrind-r05-ok' and 'ERROR SUMMARY: 0 errors' in err,'Positive program failed for '+kind)
        _,bad=run(kind+'-negative',[vg,'--tool=memcheck','--error-exitcode=97',root/(kind+'-negative')],expected=97)
        need('Invalid write of size 1' in bad,'Buffer-overflow diagnostic missing for '+kind)
        run(kind+'-client-exit-status',[vg,'--tool=memcheck','--error-exitcode=97',root/(kind+'-positive'),'23'],expected=23)
        observations[kind]={'positive':'passed','negative':'detected exit97','client_exit_code_preserved':23,'runtime_version':'2.39-0ubuntu8.6' if kind=='host' else '2.39-0ubuntu8.9'}
    outputs={}
    for tool in ('helgrind','drd','massif','cachegrind','callgrind'):
        args=[vg,'--tool='+tool,'--error-exitcode=97']
        if tool in ('massif','cachegrind','callgrind'):
            f=root/(tool+'.out');args.append('--'+tool+'-out-file='+str(f));outputs[tool]=f
        out,err=run('tool-'+tool,args+[root/'host-positive'])
        need('valgrind-r05-ok' in out,'Tool did not execute original program: '+tool)
    for name,key,args in [('cg_annotate','cachegrind',[]),('callgrind_annotate','callgrind',[]),('ms_print','massif',[])]:
        out,err=run('report-'+name,[prefix/'bin'/name,*args,outputs[key]])
        need(len(out)>50,'Empty '+name+' result')
    for name in ('vgdb',):
        run('aux-help-'+name,[prefix/'bin'/name,'--help'])
    out,_=run('private-perl-modules',[prefix/'libexec/cpg-valgrind-perl','-MConfig','-MJSON::PP','-e','print JSON::PP->new->canonical->encode({version=>"$^V",inc=>\\%INC}),"\\n"'])
    perl=json.loads(out);need(perl['version']=='v5.38.2','Private Perl version differs')
    need(all(Path(v).resolve().is_relative_to(prefix) for v in perl['inc'].values()),'Host Perl module leakage')
    for pair in profile['debug_pairs']:
        f=prefix/pair['debug_file'];need(sha(f)==pair['debug_sha256'],'Exact debug input changed')
    report={'status':'passed','prefix':str(prefix),'work':str(root),'commands':commands,'runtime_observations':observations,'runtime_fingerprints':fingerprints,'original_client_interpreter':interpreter,'original_smoke_unchanged':True,'tools':6,'private_perl':perl,'official_benchmark':'not_run','performance_claims':False}
    (root/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','original_smoke':'passed','runtime_observations':observations,'tools':6,'commands':len(commands),'evidence':str(root/'summary.json')}))
if __name__=='__main__':main()
