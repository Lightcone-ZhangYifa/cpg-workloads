#!/usr/bin/env python3
import argparse,json,os,pathlib,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);a=p.parse_args();root=pathlib.Path(a.prefix)/'bin';checks=[]
for name,expected in [('syncbench','PARALLEL time'),('schedbench','STATIC time'),('taskbench','PARALLEL TASK time')]:
    exe=root/name;env=os.environ.copy();env['OMP_NUM_THREADS']='2';argv=[str(exe),'--outer-repetitions','2','--test-time','50'];proc=subprocess.run(argv,capture_output=True,text=True,errors='replace',env=env,timeout=30)
    passed=(proc.returncode==0 and 'Running OpenMP benchmark version 3.0' in proc.stdout and expected in proc.stdout and '2 thread(s)' in proc.stdout)
    checks.append({'bin':name,'passed':passed,'argv':argv,'returncode':proc.returncode,'expected_output':expected,'stdout_tail':proc.stdout[-350:],'stderr':proc.stderr[-200:]})
status='passed' if all(x['passed'] for x in checks) else 'failed'
print(json.dumps({'status':status,'tool':'epcc-openmp','selected_3_1_CPU_tests':checks},sort_keys=True))
sys.exit(0 if status=='passed' else 1)
