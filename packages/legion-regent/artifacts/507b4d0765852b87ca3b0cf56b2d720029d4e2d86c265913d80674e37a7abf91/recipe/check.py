#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--prefix',required=True,type=Path)
p.add_argument('--work',required=True,type=Path)
a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
recipe=Path(__file__).resolve().parent
exe=a.work/'legion-consumer'
argv=[os.environ.get('CXX','g++'),'-std=c++17','-O1','-pthread','-I'+str(a.prefix/'include'),str(recipe/'consumer.cpp'),'-L'+str(a.prefix/'lib'),'-Wl,-rpath,'+str(a.prefix/'lib'),'-llegion','-lrealm','-o',str(exe)]
cp=subprocess.run(argv,capture_output=True,text=True,timeout=180)
records=[{'phase':'compile','argv':argv,'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr}]
if cp.returncode:
    (a.work/'result.json').write_text(json.dumps({'status':'failed','records':records},indent=2)+'\n')
    raise SystemExit('Legion consumer failed to compile')
expected=[{'n':n,'seed':s,'sum':sum(3*(s+i)+11 for i in range(n))} for n in (1,17,257) for s in (1,13)]
positive_env=dict(os.environ)
positive_env.pop('CPG_TEST_MUTATE',None)
for cpus in (1,2,4):
    argv=[str(exe),'-ll:cpu',str(cpus),'-ll:util','1','-ll:io','1','-ll:csize','64']
    cp=subprocess.run(argv,env=positive_env,capture_output=True,text=True,timeout=90)
    actual=[json.loads(line.split('LEGION_RESULT ',1)[1]) for line in cp.stdout.splitlines() if line.startswith('LEGION_RESULT ')]
    passed=cp.returncode==0 and actual==expected
    records.append({'phase':'execute','cpus':cpus,'argv':argv,'passed':passed,'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr})
    if not passed:
        (a.work/'result.json').write_text(json.dumps({'status':'failed','records':records},indent=2)+'\n')
        raise SystemExit('Legion result differs from independent serial oracle')
negative_argv=[str(exe),'-ll:cpu','2','-ll:util','1','-ll:io','1','-ll:csize','64']
cp=subprocess.run(negative_argv,env=dict(positive_env,CPG_TEST_MUTATE='1'),capture_output=True,text=True,timeout=90)
mutant=[json.loads(line.split('LEGION_RESULT ',1)[1]) for line in cp.stdout.splitlines() if line.startswith('LEGION_RESULT ')]
expected_mutant=[dict(row,sum=row['sum']+row['n']) for row in expected]
negative={'control':'executed_mutated_transform_rejected','argv':negative_argv,'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr,'expected_mutated_results':expected_mutant,'passed':cp.returncode==0 and mutant==expected_mutant and mutant!=expected}
out={'status':'passed' if negative['passed'] else 'failed','cases':18,'dependent_task_pairs':18,'negative_controls':[negative],'scope':'Legion C++ single-process CPU logical-region dependence; Regent/Terra, multi-rank, GPU and performance not qualified','records':records}
(a.work/'result.json').write_text(json.dumps(out,indent=2)+'\n')
if out['status']!='passed':raise SystemExit('executed Legion mutation was not rejected')
print(json.dumps({'status':'passed','cases':18,'marker':'LEGION_FUNCTIONAL_OK'}))
