import argparse,csv,json,pathlib,random,sys
import numpy as np
from hypermapper import optimizer
from benchmark import Benchmark,DEFAULT,InvalidConfiguration,clean_config,append
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
random.seed(83);np.random.seed(83);b=Benchmark(out,'hypermapper');i=0

def objective(c):
 global i;i+=1
 try:cfg=clean_config(c)
 except InvalidConfiguration as e:
  append(out/'constraint-evaluations.jsonl',{'trial':i,'config':c,'feasible':False,'valid_speed':False,'objective_seconds':None,'algorithm_penalty':8.0,'reason':str(e)})
  return {'runtime_seconds':8.0,'Valid':False}
 cost=b.evaluate(cfg,trial_id=i)
 return {'runtime_seconds':cost,'Valid':True}
scenario={'application_name':'cpg083-hypermapper','optimization_objectives':['runtime_seconds'],'optimization_iterations':10,'design_of_experiment':{'doe_type':'random sampling','number_of_samples':6},'optimization_method':'bayesian_optimization','models':{'model':'random_forest','number_of_trees':16},'feasible_output':{'enable_feasible_predictor':True,'name':'Valid','true_value':'True','false_value':'False'},'input_parameters':{'opt':{'parameter_type':'ordinal','values':[1,2,3]},'tile':{'parameter_type':'ordinal','values':[4,8,16,32]},'unroll':{'parameter_type':'ordinal','values':[0,1]},'vectorize':{'parameter_type':'ordinal','values':[0,1]}},'run_directory':str(out),'output_data_file':'samples.csv','log_file':str(out/'hypermapper.log')}
path=out/'scenario.json';path.write_text(json.dumps(scenario,indent=2))
# A deterministic infeasible probe exercises the same feasible-output interface.
r=objective({**DEFAULT,'opt':1,'unroll':1})
if r['Valid'] is not False: raise RuntimeError('Constraint gate failed')
optimizer.optimize(str(path),objective)
rows=list(csv.DictReader((out/'samples.csv').open()));feasible=[r for r in rows if r['Valid'].lower()=='true']
if not feasible:raise RuntimeError('No feasible measured output')
best=min(feasible,key=lambda r:float(r['runtime_seconds']));cfg=clean_config({k:best[k] for k in DEFAULT})
measures=[json.loads(x) for x in (out/'evaluations.jsonl').read_text().splitlines()]
if not any(m['config']==cfg and m['objective_seconds']==float(best['runtime_seconds']) for m in measures):raise RuntimeError('Output configuration does not map to recorded real measurement')
res={'status':'passed','tool':'hypermapper','seed':83,'search_evaluations':len(rows),'feasible_evaluations':len(feasible),'infeasible_penalties_are_not_measurements':True,'only_optimization_objective':'runtime_seconds','best_config':cfg,'best_train_seconds':float(best['runtime_seconds']),'replay':b.replay(cfg)}
(out/'result.json').write_text(json.dumps(res,indent=2,allow_nan=False)+'\n');print(json.dumps(res))
