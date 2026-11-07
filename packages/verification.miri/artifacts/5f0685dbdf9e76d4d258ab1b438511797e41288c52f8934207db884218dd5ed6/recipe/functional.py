"""Replay fixed safe, use-after-free, and Tree Borrows alias cases offline."""
from pathlib import Path
import tempfile
import json,os,shutil,subprocess,sys,hashlib
prefix=Path(sys.argv[1]).resolve()
evidence_root=Path.cwd()/'functional-evidence';evidence_root.mkdir(parents=True,exist_ok=True)
work=Path(tempfile.mkdtemp(prefix='run-',dir=evidence_root))
env=os.environ.copy();env.update({'MIRIFLAGS':'-Zmiri-tree-borrows','CARGO_HOME':str(work/'cargo-home'),'CARGO_NET_OFFLINE':'true','CARGO_BUILD_JOBS':'1','TMPDIR':str(work/'tmp')})
(work/'tmp').mkdir(exist_ok=True)
version=subprocess.run([str(prefix/'bin/miri'),'--version'],env=env,text=True,capture_output=True,timeout=30)
(work/'version.json').write_text(json.dumps({'returncode':version.returncode,'stdout':version.stdout,'stderr':version.stderr},indent=2)+'\n')
if version.returncode!=0 or 'miri 0.1.0 (3e92e1a2d2 2026-11-01)' not in version.stdout:raise RuntimeError('Pinned Miri version differs')
rows=[]
for name in ('safe','use_after_free','alias_violation'):
 case=work/name;shutil.copytree(prefix/'share/fixtures'/name,case)
 env['CARGO_TARGET_DIR']=str(case/'target')
 argv=[str(prefix/'bin/miri'),'run','--offline','--manifest-path',str(case/'Cargo.toml')]
 run=subprocess.run(argv,cwd=case,env=env,text=True,capture_output=True,timeout=180)
 row={'case':name,'argv':argv,'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr,'model':'Tree Borrows','source_sha256':hashlib.sha256((case/'src/main.rs').read_bytes()).hexdigest()};rows.append(row)
 for stream in ('stdout','stderr'):(work/(name+'.'+stream+'.log')).write_text(row[stream])
 (work/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n')
 if name=='safe':
  if run.returncode!=0 or 'safe_sum=14' not in run.stdout:raise RuntimeError('Safe execution did not succeed: '+json.dumps(row))
 else:
  if run.returncode!=1 or 'Undefined Behavior' not in run.stderr:raise RuntimeError('Expected UB was not diagnosed: '+json.dumps(row))
  if name=='use_after_free' and not ('freed' in run.stderr or 'deallocated' in run.stderr or 'dangling' in run.stderr):raise RuntimeError('Use-after-free diagnostic missing: '+json.dumps(row))
  if name=='alias_violation' and not ('Tree Borrows' in run.stderr or 'protected' in run.stderr or 'forbidden' in run.stderr):raise RuntimeError('Aliasing diagnostic missing: '+json.dumps(row))
print(json.dumps({'status':'passed','resource':'verification.miri','nightly':'2026-11-02','checks':rows},ensure_ascii=False))
