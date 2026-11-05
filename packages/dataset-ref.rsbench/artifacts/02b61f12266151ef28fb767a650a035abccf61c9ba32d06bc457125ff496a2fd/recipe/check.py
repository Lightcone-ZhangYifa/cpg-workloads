#!/usr/bin/env python3
import argparse, os, subprocess, json, pathlib, sys
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True); a=p.parse_args()
exe=pathlib.Path(a.prefix)/'bin/rsbench'
if not exe.is_file() or exe.is_symlink() or not os.access(exe,os.X_OK):
    print(json.dumps({'status':'failed','reason':'installed executable missing or invalid'}));sys.exit(1)
checks=[]
for n in [1]:
    env=os.environ.copy(); env['OMP_NUM_THREADS']=str(n)
    argv=[str(exe)] + ["-s","small","-t","1"]
    proc=subprocess.run(argv,env=env,capture_output=True,text=True,errors='replace',timeout=100)
    expected='Verification checksum: 879693 (Valid)'
    passed=(proc.returncode==0 and expected in proc.stdout and 'WARNING' not in proc.stdout)
    checks.append({'threads':n,'returncode':proc.returncode,'expected_string':expected,'passed':passed,'tail':proc.stdout[-700:],'stderr':proc.stderr[-400:]})
status='passed' if all(x['passed'] for x in checks) else 'failed'
print(json.dumps({'status':status,'tool':'rsbench','upstream_functional_checks':checks},sort_keys=True))
sys.exit(0 if status=='passed' else 1)
