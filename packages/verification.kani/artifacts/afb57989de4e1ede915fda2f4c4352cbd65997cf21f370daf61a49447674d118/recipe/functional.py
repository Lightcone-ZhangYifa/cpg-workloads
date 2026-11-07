"""Require correct finite-domain proof, a real counterexample, and unwind failure."""
from pathlib import Path
import tempfile
import hashlib,json,os,shutil,subprocess,sys
prefix=Path(sys.argv[1]).resolve()
evidence_root=Path.cwd()/'functional-evidence';evidence_root.mkdir(parents=True,exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='run-',dir=evidence_root))
env=os.environ.copy();env.update({'CARGO_NET_OFFLINE':'true','CARGO_BUILD_JOBS':'1','RAYON_NUM_THREADS':'1','TERM':'dumb','NO_COLOR':'1'})
version=subprocess.run([str(prefix/'bin/kani'),'--version'],env=env,text=True,capture_output=True,timeout=60)
(work/'version.json').write_text(json.dumps({'returncode':version.returncode,'stdout':version.stdout,'stderr':version.stderr},indent=2)+'\n')
if version.returncode!=0 or 'Kani Rust Verifier 0.68.0' not in version.stdout or 'CBMC 6.11.0' not in version.stdout:raise RuntimeError('Pinned Kani/CBMC version differs')
rows=[]
for name,harness,bound in [('positive','popcount4_matches_reference',5),('negative','deliberately_false_bound',5),('insufficient_unwind','popcount4_matches_reference',2)]:
 case=work/name;case.mkdir();source=case/'popcount.rs';shutil.copy2(prefix/'share/fixtures/popcount.rs',source)
 report=case/'verification.json'
 argv=[str(prefix/'bin/kani'),str(source),'--harness',harness,'--exact','--unwind',str(bound),'--keep-temps','-Z','unstable-options','--export-json',str(report)]
 if name=='negative':argv+=['-Z','concrete-playback','--concrete-playback=print']
 run=subprocess.run(argv,cwd=case,env=env,text=True,capture_output=True,timeout=240)
 row={'case':name,'harness':harness,'unwind':bound,'domain_cardinality':16,'argv':argv,'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()};rows.append(row)
 for stream in ('stdout','stderr'):(work/(name+'.'+stream+'.log')).write_text(row[stream])
 (work/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n')
 if not report.exists():raise RuntimeError('No actual Kani verification report: '+json.dumps(row))
 proof=json.loads(report.read_text());summary=proof.get('verification_results',{}).get('summary',{})
 if summary.get('executed')!=1 or summary.get('total_harnesses')!=1:raise RuntimeError('Wrong harness execution count: '+json.dumps(proof))
 if name=='positive':
  if run.returncode!=0 or 'VERIFICATION:- SUCCESSFUL' not in run.stdout or summary.get('successful')!=1 or summary.get('failed')!=0:raise RuntimeError('Correct property was not proved: '+json.dumps(row))
 else:
  if run.returncode!=1 or 'VERIFICATION:- FAILED' not in run.stdout or summary.get('failed')!=1:raise RuntimeError('Expected negative verification result absent: '+json.dumps(row))
  details=proof.get('error_details',[])
  if not any(x.get('exit_status')=='properties_failed' for x in details):raise RuntimeError('Negative case was a tool failure, not a property failure: '+json.dumps(proof))
  if name=='negative':
   if 'deliberately false: value 15 has four set bits' not in run.stdout or 'Concrete playback unit test' not in run.stdout or 'vec![15]' not in run.stdout:raise RuntimeError('The expected concrete counterexample was not preserved: '+json.dumps(row))
  elif 'unwinding assertion loop' not in run.stdout:raise RuntimeError('Missing insufficient-unwind diagnostic: '+json.dumps(row))
print(json.dumps({'status':'passed','resource':'verification.kani','domain_cardinality':16,'checks':rows},ensure_ascii=False))
