#!/usr/bin/env python3
"""Run Intel's original inscount0 on newly generated, owned test programs."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,time
def run(argv,cwd,log,timeout=120):
    start=time.monotonic();p=subprocess.run([str(x) for x in argv],cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    log.append({'argv':[str(x) for x in argv],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'seconds':time.monotonic()-start})
    if p.returncode:raise RuntimeError('Command failed: '+str(argv)+'\n'+p.stderr)
    return p
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--kit',required=True);ap.add_argument('--client',required=True);ap.add_argument('--out',required=True);args=ap.parse_args()
    kit=Path(args.kit).resolve();client=Path(args.client).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False)
    commands=[];result={'status':'failed','scope':'owned x86_64 C fixture; local instruction-count API; no system profiling','commands':commands}
    try:
        if not client.is_file():raise RuntimeError('installed original-example client is absent')
        source=out/'owned_loop.c';source.write_text('#include <stdio.h>\n#include <stdlib.h>\nint main(int argc,char **argv){if(argc!=2)return 2;unsigned long n=strtoul(argv[1],0,10);if(n>100000)return 3;volatile unsigned long long sum=0;for(unsigned long i=0;i<n;i++)sum+=(i^(3*i));printf("n=%lu checksum=%llu\\n",n,sum);return 0;}\n')
        binary=out/'owned_loop';run(['gcc','-O0','-fno-pie','-no-pie',source,'-o',binary],out,commands)
        cases=[]
        for n in (100,1000,10000):
            expected=f'n={n} checksum={sum(i^(3*i) for i in range(n))}\n';baseline=run([binary,n],out,commands);countfile=out/f'inscount-{n}.out'
            instrumented=run([kit/'pin','-t',client,'-o',countfile,'--',binary,n],out,commands)
            if baseline.stdout!=expected or instrumented.stdout!=expected:raise RuntimeError('arithmetic oracle or preserved stdout mismatch')
            match=re.fullmatch(r'Count\s+(\d+)\s*',countfile.read_text())
            if not match or int(match[1])<=0:raise RuntimeError('missing positive instruction count')
            cases.append({'iterations':n,'expected_stdout':expected,'observed_stdout':instrumented.stdout,'instruction_count':int(match[1])})
        if not(cases[0]['instruction_count']<cases[1]['instruction_count']<cases[2]['instruction_count']):raise RuntimeError('loop workload counts are not increasing')
        result.update(status='passed',cases=cases,client_sha256=hashlib.sha256(client.read_bytes()).hexdigest(),tool_source_sha256=hashlib.sha256((kit/'source/tools/ManualExamples/inscount0.cpp').read_bytes()).hexdigest(),limitations=['Client compiled once during installation and protected by the installed inventory.','Counts cover the launched program and its runtime, not system-wide performance.','No IA32, Windows, VTune or SDE qualification.'])
    except Exception as e:result['error']=str(e);raise
    finally:(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'cases':result['cases']}))
if __name__=='__main__':main()
