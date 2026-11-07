import argparse,json,pathlib,tempfile,os,shutil
import ray
from ray import tune
from ray.tune import Checkpoint,RunConfig,FailureConfig
from benchmark import Benchmark,DEFAULT

def compile_trial(config):
 context=tune.get_context();trial_dir=pathlib.Path(context.get_trial_dir());b=Benchmark(trial_dir/'measurement','ray',os.environ['CPG_ORACLES'])
 restored=tune.get_checkpoint();start=0
 if restored:
  with restored.as_directory() as d:state=json.loads((pathlib.Path(d)/'state.json').read_text())
  if state['config']!=config or state['trial_id']!=context.get_trial_id():raise RuntimeError('Checkpoint attached to different trial/configuration')
  start=state['next_step']
 for step in range(start,2):
  value=b.evaluate(config,trial_id=context.get_trial_id(),phase='restored_trial' if restored else 'search')
  with tempfile.TemporaryDirectory(dir=trial_dir) as d:
   pathlib.Path(d,'state.json').write_text(json.dumps({'config':config,'next_step':step+1,'trial_id':context.get_trial_id()}))
   tune.report({'runtime_seconds':value,'restored_from_checkpoint':bool(restored),'step':step+1},checkpoint=Checkpoint.from_directory(d))
  if step==0 and not restored:raise RuntimeError('CPG deliberate checkpoint-resume interruption')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--phase',choices=['start','resume'],required=True);a=p.parse_args();out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
 os.environ['PYTHONPATH']=str(pathlib.Path(__file__).resolve().parent)+os.pathsep+os.environ.get('PYTHONPATH','');os.environ['RAY_USAGE_STATS_ENABLED']='0';os.environ['CPG_ORACLES']=str(out.parent/'oracles.json');os.environ['TUNE_DISABLE_AUTO_CALLBACK_LOGGERS']='1'
 raytmp=tempfile.mkdtemp(prefix='w083-ray-',dir='/tmp')
 try:
  ray.init(local_mode=True,num_cpus=1,include_dashboard=False,_node_ip_address="127.0.0.1",_temp_dir=raytmp,object_store_memory=90*1024*1024,log_to_driver=False)
  expt=out/'storage'/'cpg083'
  if a.phase=='start':
   t=tune.Tuner(compile_trial,param_space={'opt':tune.grid_search([1,2,3]),'tile':8,'unroll':0,'vectorize':1},tune_config=tune.TuneConfig(metric='runtime_seconds',mode='min',max_concurrent_trials=1),run_config=RunConfig(name='cpg083',storage_path=str(out/'storage'),failure_config=FailureConfig(max_failures=0),verbose=0))
   results=t.fit();errors=sum(r.error is not None for r in results)
   if errors!=3:raise RuntimeError(f'Expected 3 controlled interruptions, got {errors}')
   checkpoint_count=sum(r.checkpoint is not None for r in results)
   if checkpoint_count!=3:raise RuntimeError(f'All 3 trials must persist a real checkpoint, got {checkpoint_count}')
   (out/'phase1.json').write_text(json.dumps({'deliberately_interrupted_trials':errors,'checkpoint_count':sum(r.checkpoint is not None for r in results)},indent=2));print('CHECKPOINT_INTERRUPTED 3')
  else:
   if not tune.Tuner.can_restore(str(expt)):raise RuntimeError('Experiment not restorable')
   t=tune.Tuner.restore(str(expt),trainable=compile_trial,resume_errored=True);results=t.fit()
   if len(results)!=3 or any(r.error for r in results):raise RuntimeError('Restored trials failed')
   if not all(r.metrics['restored_from_checkpoint'] and r.metrics['step']==2 for r in results):raise RuntimeError('Checkpoints were not resumed at correct step')
   best=results.get_best_result(metric='runtime_seconds',mode='min');b=Benchmark(out,'ray-replay')
   report={'status':'passed','tool':'ray-tune','version':ray.__version__,'local_only':True,'execution_mode':'Ray local_mode=True; real Tune scheduler and persisted trial checkpoints with external measured C executables; no distributed-cluster claim','num_cpus':1,'total_trials':3,'controlled_interruptions':3,'restored_checkpoint_trials':3,'best_config':best.config,'trial_results':[{'config':r.config,'runtime_seconds':r.metrics['runtime_seconds'],'restored':r.metrics['restored_from_checkpoint'],'step':r.metrics['step']} for r in results],'replay':b.replay(best.config)}
   (out/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report))
 finally:ray.shutdown();shutil.rmtree(raytmp,ignore_errors=True)
