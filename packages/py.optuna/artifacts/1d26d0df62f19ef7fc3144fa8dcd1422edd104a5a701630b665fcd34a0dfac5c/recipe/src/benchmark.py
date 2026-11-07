"""Real GCC compilation and measured C execution; no generated/surrogate objectives."""
from __future__ import annotations
import argparse,hashlib,json,math,os,pathlib,statistics,subprocess,tempfile,time
HERE=pathlib.Path(__file__).resolve().parent
INSTANCES={
 'train-a':{'n':32,'rounds':32,'seed':11},
 'train-b':{'n':48,'rounds':16,'seed':19},
 'train-c':{'n':64,'rounds':8,'seed':23},
 'test-a':{'n':40,'rounds':20,'seed':101},
 'test-b':{'n':56,'rounds':12,'seed':103},
 'test-c':{'n':72,'rounds':6,'seed':107}}
DEFAULT={'opt':2,'tile':8,'unroll':0,'vectorize':1}
class EvaluationError(RuntimeError): pass
class CompileFailure(EvaluationError): pass
class IncorrectResult(EvaluationError): pass
class EvaluationTimeout(EvaluationError): pass
class InvalidConfiguration(EvaluationError): pass

def clean_config(c):
 c=dict(c); required=set(DEFAULT)
 if set(c)!=required: raise InvalidConfiguration(f'Expected {sorted(required)}; got {sorted(c)}')
 for k,v in c.items():
  try:
   f=float(v); n=int(v)
  except (ValueError,TypeError,OverflowError) as e: raise InvalidConfiguration('Noninteger value: '+k) from e
  if not math.isfinite(f) or f != n: raise InvalidConfiguration('Noninteger value: '+k)
 c={k:int(v) for k,v in c.items()}
 if c['opt'] not in [1,2,3] or c['tile'] not in [4,8,16,32] or c['unroll'] not in [0,1] or c['vectorize'] not in [0,1]: raise InvalidConfiguration('Outside allowlisted compile-parameter domain')
 if c['opt']==1 and c['unroll']==1: raise InvalidConfiguration('unroll requires optimization level 2 or 3')
 return c

def argv_for(c):
 return ['gcc','-std=c11',f"-O{c['opt']}",f"-DTILE={c['tile']}",'-funroll-loops' if c['unroll'] else '-fno-unroll-loops','-ftree-vectorize' if c['vectorize'] else '-fno-tree-vectorize']

def append(path,row):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a') as f:f.write(json.dumps(row,sort_keys=True)+'\n')

def python_reference(n,rounds,seed):
 a=[(i*17+seed*13)%251 for i in range(n*n)];b=[(i*29+seed*7)%127 for i in range(n*n)];h=1469598103934665603
 for r in range(rounds):
  a[r%(n*n)]+=r+1
  for i in range(n):
   for j in range(n):
    v=sum(a[i*n+k]*b[k*n+j] for k in range(n)) & 0xffffffff
    h=((h ^ v)*1099511628211)&0xffffffffffffffff
 return h

def make_oracles(out):
 out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='oracle-',dir=out) as d:
  exe=pathlib.Path(d)/'reference'; cmd=['gcc','-std=c11','-O0','-DREFERENCE=1',str(HERE/'kernel.c'),'-o',str(exe)]
  subprocess.run(cmd,check=True,capture_output=True)
  small={}
  for n,r,s in [(3,2,1),(7,3,17),(9,1,41)]:
   a=subprocess.check_output([str(exe),str(n),str(r),str(s)],text=True).split()
   expected=python_reference(n,r,s)
   if int(a[1])!=expected: raise IncorrectResult('Independent Python/C oracle mismatch')
   small[f'{n},{r},{s}']={'python_checksum':expected,'C_reference_checksum':int(a[1])}
  cases={}
  for k,v in INSTANCES.items():
   a=subprocess.check_output([str(exe),str(v['n']),str(v['rounds']),str(v['seed'])],text=True).split()
   cases[k]={**v,'checksum':int(a[1])}
 data={'schema_version':1,'source_sha256':hashlib.sha256((HERE/'kernel.c').read_bytes()).hexdigest(),'reference_command':cmd,'independent_small_checks':small,'instances':cases,'train_instances':[k for k in cases if k.startswith('train')],'heldout_instances':[k for k in cases if k.startswith('test')]}
 (out/'oracles.json').write_text(json.dumps(data,indent=2)+'\n');return data

class Benchmark:
 def __init__(self,evidence,tool,oracles=None):
  self.evidence=pathlib.Path(evidence).resolve();self.evidence.mkdir(parents=True,exist_ok=True);self.tool=tool
  p=pathlib.Path(oracles) if oracles else self.evidence.parent/'oracles.json'
  self.oracles=json.loads(p.read_text());self.counter=0
 def evaluate(self,config,instance='train-a',repeats=3,phase='search',fault=None,trial_id=None):
  self.counter+=1; uid=f'{self.tool}-{os.getpid()}-{self.counter}-{time.monotonic_ns()}'
  row={'evaluation_id':uid,'trial_id':trial_id,'tool':self.tool,'config':dict(config),'instance':instance,'phase':phase,'fault_injection':fault,'status':'started','valid_speed':False,'objective_seconds':None}
  stamp=time.perf_counter()
  try:
   c=clean_config(config);row['config']=c
   if instance not in self.oracles['instances']: raise InvalidConfiguration('Unregistered instance')
   with tempfile.TemporaryDirectory(prefix='compile-',dir=self.evidence) as d:
    exe=pathlib.Path(d)/'kernel';cmd=argv_for(c)+([f'-D{fault}'] if fault in ['FAULT_TIMEOUT','FAULT_WRONG'] else [])+[str(HERE/'kernel.c'),'-o',str(exe)]
    if fault=='FAULT_COMPILE':cmd.insert(1,'-fdefinitely-not-a-valid-cpg-option')
    t=time.perf_counter(); cp=subprocess.run(cmd,text=True,capture_output=True,timeout=30); row.update(compile_seconds=time.perf_counter()-t,compile_command=cmd,compiler_returncode=cp.returncode,compiler_stderr=cp.stderr)
    if cp.returncode:raise CompileFailure(cp.stderr)
    row['binary_sha256']=hashlib.sha256(exe.read_bytes()).hexdigest();v=self.oracles['instances'][instance]
    timings=[]; outputs=[]; row['raw_runs']=outputs
    for i in range(repeats+1):
     try:r=subprocess.run([str(exe),str(v['n']),str(v['rounds']),str(v['seed'])],text=True,capture_output=True,timeout=0.15 if fault=='FAULT_TIMEOUT' else 8)
     except subprocess.TimeoutExpired as e:raise EvaluationTimeout('Timed out without any valid speed sample') from e
     outputs.append({'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'warmup':i==0})
     if r.returncode:raise EvaluationError(f'Program failed {r.returncode}')
     fields=r.stdout.strip().split()
     if len(fields)!=2:raise IncorrectResult('Invalid kernel output')
     ns,checksum=map(int,fields)
     if checksum!=v['checksum']:raise IncorrectResult(f'Expected checksum {v["checksum"]}; got {checksum}')
     seconds=ns*1e-9
     if not math.isfinite(seconds) or seconds<=0:raise EvaluationError('Nonpositive/nonfinite runtime')
     if i:timings.append(seconds)
    row.update(status='ok',valid_speed=True,objective_seconds=statistics.median(timings),samples_seconds=timings,raw_runs=outputs,checksum=v['checksum'])
  except Exception as e:
   row.update(status=type(e).__name__,error=str(e),valid_speed=False,objective_seconds=None)
   append(self.evidence/'evaluations.jsonl',row)
   raise
  row['elapsed_wall_seconds']=time.perf_counter()-stamp;append(self.evidence/'evaluations.jsonl',row);return row['objective_seconds']
 def objective(self,c,**kw):return self.evaluate(c,**kw)
 def replay(self,config):
  results={k:self.evaluate(config,k,phase='heldout_replay') for k in self.oracles['heldout_instances']}
  return {'config':clean_config(config),'heldout_objectives_seconds':results,'heldout_geomean_seconds':math.exp(sum(math.log(v) for v in results.values())/len(results))}

def negatives(out):
 out=pathlib.Path(out); b=Benchmark(out/'negative','negative',out/'oracles.json');cases={}
 for name,f,c,kind in [('wrong','FAULT_WRONG',DEFAULT,IncorrectResult),('compile','FAULT_COMPILE',DEFAULT,CompileFailure),('timeout','FAULT_TIMEOUT',DEFAULT,EvaluationTimeout),('constraint',None,{**DEFAULT,'opt':1,'unroll':1},InvalidConfiguration),('fractional',None,{**DEFAULT,'tile':8.5},InvalidConfiguration)]:
  try:b.evaluate(c,fault=f,phase='negative_control')
  except kind:cases[name]={'rejected':True,'expected_exception':kind.__name__}
  else:raise AssertionError(name)
 (out/'negative-controls.json').write_text(json.dumps(cases,indent=2)+'\n');return cases
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--prepare');p.add_argument('--evaluate');p.add_argument('--evidence');p.add_argument('--tool',default='external');p.add_argument('--instance',default='train-a');p.add_argument('--trial-id');a=p.parse_args()
 if a.prepare:make_oracles(a.prepare);print(json.dumps(negatives(a.prepare)))
 else: print(Benchmark(a.evidence,a.tool).evaluate(json.loads(a.evaluate),a.instance,repeats=2,trial_id=a.trial_id))
