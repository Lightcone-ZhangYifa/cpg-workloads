#!/usr/bin/env python3
"""Actual AFL++ forkserver and fuzzing execution, not a version/help probe."""
import argparse,hashlib,json,os,pathlib,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--build',required=True);a=p.parse_args()
prefix=pathlib.Path(a.prefix)
fuzzer=prefix/'bin/afl-fuzz'
assert fuzzer.is_file() and os.access(fuzzer,os.X_OK)
with tempfile.TemporaryDirectory(prefix='cpg-afl-functional-',dir=a.build) as td:
 work=pathlib.Path(td)
 harness=work/'target'; source=work/'target.c'
 source.write_text('#include <stdio.h>\nint main(){char x[64];fgets(x,sizeof(x),stdin);puts("processed");return 0;}\n')
 build=subprocess.run(['gcc','-O2',str(source),'-o',str(harness)],capture_output=True,text=True,timeout=30)
 assert build.returncode==0,build.stderr
 corpus=work/'in'; corpus.mkdir();(corpus/'seed').write_text('A\n')
 env={**os.environ,'AFL_NO_UI':'1','AFL_SKIP_CPUFREQ':'1',
      'AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES':'1','AFL_NO_AFFINITY':'1'}
 args=[str(fuzzer),'-n','-E','800','-i',str(corpus),'-o',str(work/'out'),'--',str(harness)]
 proc=subprocess.run(args,env=env,capture_output=True,text=True,timeout=45)
 if proc.returncode!=0 or 'Execution limit was reached' not in proc.stdout or 'old fork server is up' not in proc.stderr:
  print('real fuzz failed',proc.returncode,proc.stdout[-2000:],proc.stderr[-1000:])
  raise RuntimeError('Real AFL++ forkserver/fuzz functional check failed')
 assert any((work/'out'/'queue').glob('id:*'))
 print(json.dumps({'status':'passed','kind':'functional','resource':'aflplusplus',
  'mode':'native_core_binary_only_-n_no_instrumentation',
  'target_compiler':'gcc','execution_cap':800,'fuzzer_exit':0,
  'stdout_sha256':hashlib.sha256(proc.stdout.encode()).hexdigest(),
  'stderr_sha256':hashlib.sha256(proc.stderr.encode()).hexdigest(),
  'full_distrib_qualified':False,'coverage_instrumentation_qualified':False},sort_keys=True))
