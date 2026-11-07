#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

p=argparse.ArgumentParser();p.add_argument('--prefix',required=True,type=Path);p.add_argument('--work',required=True,type=Path)
a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);recipe=Path(__file__).resolve().parent
if (a.prefix/'bin').exists():raise SystemExit('CPU runtime profile must not ship unqualified auxiliary executables')
headers=list((a.prefix/'include').glob('starpu/*/starpu.h'))
if len(headers)!=1:raise SystemExit('exact StarPU include version is ambiguous or absent')
lib=a.prefix/'lib';exe=a.work/'starpu-consumer'
pc=lib/'pkgconfig/starpu-1.4.pc';pc_text=pc.read_text()
variables={'pcfiledir':str(pc.parent.resolve())}
for line in pc_text.splitlines():
    if re.match(r'^[A-Za-z_][A-Za-z_0-9]*=',line):
        key,value=line.split('=',1);variables[key]=value
def expand(value):
    for _ in range(20):
        replacement=re.sub(r'\$\{([^}]+)\}',lambda m:variables[m.group(1)],value)
        if replacement==value:return replacement
        value=replacement
    raise ValueError('cyclic pkg-config variables')
if variables.get('prefix')!='${pcfiledir}/../..':raise SystemExit('pkg-config prefix is not relative')
if Path(expand(variables['prefix'])).resolve()!=a.prefix.resolve():raise SystemExit('pkg-config resolves wrong prefix')
if Path(expand(variables['libdir'])).resolve()!=lib.resolve():raise SystemExit('pkg-config resolves wrong libdir')
if Path(expand(variables['starpu_includedir'])).resolve()!=headers[0].parent.resolve():raise SystemExit('pkg-config resolves wrong includedir')
argv=[os.environ.get('CC','gcc'),'-std=c11','-O1','-march=x86-64','-mtune=generic','-pthread','-I'+str(headers[0].parent),str(recipe/'consumer.c'),'-L'+str(lib),'-Wl,-rpath,'+str(lib),'-lstarpu-1.4','-o',str(exe)]
cp=subprocess.run(argv,capture_output=True,text=True,timeout=600);records=[dict(phase='pkgconfig-metadata',status='passed',mechanism='bounded variable expansion; external pkg-config executable not required or claimed',prefix=expand(variables['prefix']),libdir=expand(variables['libdir']),includedir=expand(variables['starpu_includedir'])),dict(phase='compile',argv=argv,returncode=cp.returncode,stdout=cp.stdout,stderr=cp.stderr)]
if cp.returncode:
    (a.work/'result.json').write_text(json.dumps({'status':'failed','records':records},indent=2)+'\n');raise SystemExit('StarPU consumer compilation failed')
home=a.work/'starpu-home';home.mkdir(exist_ok=True)
env=dict(os.environ,STARPU_HOME=str(home),STARPU_WORKERS_NOBIND='1',STARPU_SILENT='1',STARPU_NCUDA='0',STARPU_NOPENCL='0',STARPU_NHIP='0',OMP_NUM_THREADS='1',OMP_THREAD_LIMIT='1')
env.pop('CPG_TEST_MUTATE',None)
for cpus in (1,2,4):
    for n in (1,17,257):
        for seed in (0,13):
            cp=subprocess.run([str(exe),str(cpus),str(n),str(seed)],env=env,capture_output=True,text=True,timeout=45)
            actual=json.loads(cp.stdout) if cp.returncode==0 else None
            expected=dict(cpus=cpus,n=n,seed=seed,cpu_workers=cpus,result=[3*(seed+i)+11 for i in range(n)])
            passed=cp.returncode==0 and actual==expected
            records.append(dict(phase='execute',cpus=cpus,n=n,seed=seed,passed=passed,returncode=cp.returncode,stdout=cp.stdout,stderr=cp.stderr))
            if not passed:
                (a.work/'result.json').write_text(json.dumps({'status':'failed','records':records},indent=2)+'\n');raise SystemExit('StarPU data-dependency result differs from serial oracle')
negative=[]
cp=subprocess.run([str(exe),'0','17','13'],env=env,capture_output=True,text=True,timeout=45)
negative.append(dict(control='invalid_zero_workers',expected_returncode=2,returncode=cp.returncode,stdout=cp.stdout,stderr=cp.stderr,passed=cp.returncode==2))
cp=subprocess.run([str(exe),'2','17','13'],env=dict(env,CPG_TEST_MUTATE='1'),capture_output=True,text=True,timeout=45)
mutant=json.loads(cp.stdout) if cp.returncode==0 else None
serial=dict(cpus=2,n=17,seed=13,cpu_workers=2,result=[3*(13+i)+11 for i in range(17)])
expected_mutant=dict(cpus=2,n=17,seed=13,cpu_workers=2,result=[3*(13+i)+12 for i in range(17)])
negative.append(dict(control='executed_mutated_bias_rejected',returncode=cp.returncode,stdout=cp.stdout,stderr=cp.stderr,passed=cp.returncode==0 and mutant!=serial and mutant==expected_mutant))
out=dict(status='passed' if all(x['passed'] for x in negative) else 'failed',cases=18,dependent_codelets=2,negative_controls=negative,scope='CPU only; no GPU/MPI/performance qualification',workers=[1,2,4],sizes=[1,17,257],seeds=[0,13],oracle='exact integer vector 3*(seed+i)+11 after two RW codelets without an intervening host wait',records=records)
(a.work/'result.json').write_text(json.dumps(out,indent=2)+'\n')
if out['status']!='passed':raise SystemExit('StarPU negative controls failed')
print(json.dumps({'status':'passed','cases':18,'marker':'STARPU_FUNCTIONAL_OK'}))
