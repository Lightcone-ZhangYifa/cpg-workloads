#!/usr/bin/env python3
"""Run unchanged upstream topology command cases with every assertion enforced."""
import argparse,datetime,hashlib,json,os,shlex,subprocess
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 root=a.prefix.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 origin=root/'share/likwid/source/test/executable_tests/likwid-topology.txt';data=origin.read_bytes();(out/'original-likwid-topology.txt').write_bytes(data)
 rows=[];env=dict(os.environ,LC_ALL='C');env.pop('LD_PRELOAD',None);env.pop('LD_LIBRARY_PATH',None)
 for index,line in enumerate(data.decode().splitlines(),1):
  if not line.strip() or line.startswith('#'):continue
  if '/tmp/out' in line:continue
  clauses=[x.strip() for x in line.split('|')];argv=[str(root/'bin/likwid-topology'),*shlex.split(clauses[0])]
  run=subprocess.run(argv,cwd=out,env=env,capture_output=True,text=True,timeout=90)
  text=run.stdout+run.stderr;(out/f'{index:02d}.stdout').write_text(run.stdout);(out/f'{index:02d}.stderr').write_text(run.stderr)
  checks=[]
  for clause in clauses[1:]:
   command,arg=clause.split(None,1)
   if command.upper()=='EXIT':ok=run.returncode==int(arg)
   elif command.upper() in ('GREP','NGREP'):
    g=subprocess.run(['grep','--',arg],input=text,capture_output=True,text=True)
    assert g.returncode in (0,1)
    ok=(g.returncode==0)==(command.upper()=='GREP')
   else:raise ValueError('Unrecognized original assertion: '+command)
   checks.append({'original_clause':clause,'passed':ok})
  rows.append({'line':index,'original_case':line,'argv':argv,'returncode':run.returncode,'assertions':checks,'status':'passed' if all(x['passed'] for x in checks) else 'failed'})
 report={'schema_version':1,'resource_id':'likwid','status':'passed' if len(rows)==12 and all(x['status']=='passed' for x in rows) else 'failed','completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_test_file_sha256':hashlib.sha256(data).hexdigest(),'source_input_unchanged':True,'execution':{'selected_cases':len(rows),'passed':sum(x['status']=='passed' for x in rows),'failed':sum(x['status']=='failed' for x in rows),'assertions':sum(len(x['assertions']) for x in rows),'unselected_cases':2,'selection_reason':'All twelve upstream read-only topology command cases; two /tmp/out filesystem output cases remain unselected to avoid shared fixed output paths.','harness_note':'Each original EXIT/GREP condition is checked conjunctively; original lowercase grep clause is checked too. Unlike the upstream shell loop this runner does not overwrite earlier predicate failures.'},'cases':rows,'hardware_counter_collection':False,'daemon_execution':False,'official_benchmark_score':False}
 (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'execution':report['execution']}));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
