import argparse,json,pathlib,subprocess,sys,concurrent.futures,time,hashlib,importlib.metadata
from ConfigSpace import ConfigurationSpace,Categorical,Configuration,ForbiddenAndConjunction,ForbiddenEqualsClause
from ytopt.search.optimizer import Optimizer
from benchmark import Benchmark
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
cs=ConfigurationSpace(seed=83);mode=Categorical('mode',['O1','O2','O3','O2-unroll','O3-unroll'],default='O2');tile=Categorical('tile',[4,8,16,32],default=8);vec=Categorical('vectorize',[0,1],default=1);cs.add([mode,tile,vec]);cs.add(ForbiddenAndConjunction(ForbiddenEqualsClause(mode,'O1'),ForbiddenEqualsClause(tile,32)))
try: Configuration(cs,values={'mode':'O1','tile':32,'vectorize':1})
except ValueError:pass
else:raise RuntimeError('Forbidden configuration accepted')
opt=Optimizer(num_workers=2,space=cs,learner='RF',acq_func='EI',liar_strategy='cl_max',set_KAPPA=1.96,set_SEED=83,set_NI=4)
submissions=[];finished=[];rows=[]
def evaluate(c,token,delay):
 d=out/'trials'/token;d.mkdir(parents=True)
 cmd=[sys.executable,'-S',str(pathlib.Path(__file__).with_name('ytopt_target.py')),'--config',json.dumps(c),'--evidence',str(d),'--oracles',str(out.parent/'oracles.json'),'--token',token,'--delay',str(delay)]
 r=subprocess.run(cmd,text=True,capture_output=True,timeout=60);(d/'stdout.log').write_text(r.stdout);(d/'stderr.log').write_text(r.stderr)
 if r.returncode:raise RuntimeError(r.stderr)
 result=json.loads(r.stdout.splitlines()[-1])
 if result['token']!=token or result['configuration']!=c:raise RuntimeError('Async result belongs to wrong configuration')
 return result
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
 for batch in range(6):
  configs=opt.ask_initial(2) if batch==0 else list(opt.ask(n_points=2,batch_size=2))[0];futures={}
  for j,c in enumerate(configs):
   c={k:(v.item() if hasattr(v,'item') else v) for k,v in c.items()};token=f'b{batch}-j{j}';submissions.append(token);futures[executor.submit(evaluate,c,token,1.0 if batch==0 and j==0 else 0)]=(c,token)
  for future in concurrent.futures.as_completed(futures):
   c,token=futures[future];r=future.result();finished.append(token);rows.append(r);opt.tell([(c,r['runtime_seconds'])])
if set(submissions)!=set(finished) or len(rows)!=12:raise RuntimeError('Lost or duplicated async completion')
if finished[:2]==submissions[:2]:raise RuntimeError('Forced out-of-order control did not complete out of order')
best=min(rows,key=lambda r:r['runtime_seconds']);b=Benchmark(out,'ytopt-replay')
report={'status':'passed','tool':'ytopt','seed':83,'budget':12,'actual_measurements':12,'conditional_domain':'mode encodes legal opt/unroll pairs; explicit forbidden O1+tile32','forbidden_configuration_rejected':True,'async_backend':'bounded local subprocesses via concurrent.futures; actual upstream ytopt Optimizer ask/tell','submitted':submissions,'completed':finished,'out_of_order_verified':True,'each_result_token_and_config_verified':True,'trials':rows,'best_config':best['compiled_configuration'],'replay':b.replay(best['compiled_configuration'])}
(out/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report))
