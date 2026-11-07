import argparse,json,pathlib,tempfile,os,shutil
import ray
from ray import tune
from ray.tune import RunConfig,FailureConfig,CheckpointConfig
from benchmark import Benchmark,DEFAULT

class CompileTrial(tune.Trainable):
 def setup(self,config):
  self.next_step=0;self.restored_from_checkpoint=False
  self.benchmark=Benchmark(pathlib.Path(os.environ['CPG_RAY_EVIDENCE'])/self.trial_id,'ray',os.environ['CPG_ORACLES'])
 def step(self):
  if self.next_step==1 and not self.restored_from_checkpoint:
   raise RuntimeError('CPG deliberate checkpoint-resume interruption')
  if self.next_step>=2:raise RuntimeError('Trial exceeded its real measurement budget')
  value=self.benchmark.evaluate(self.config,trial_id=self.trial_id,phase='restored_trial' if self.restored_from_checkpoint else 'search')
  self.next_step+=1
  return {'runtime_seconds':value,'restored_from_checkpoint':self.restored_from_checkpoint,'step':self.next_step,'done':self.next_step==2}
 def save_checkpoint(self,checkpoint_dir):
  state={'config':self.config,'next_step':self.next_step,'trial_id':self.trial_id}
  pathlib.Path(checkpoint_dir,'state.json').write_text(json.dumps(state,allow_nan=False)+'\n')
  return checkpoint_dir
 def load_checkpoint(self,checkpoint_dir):
  state=json.loads(pathlib.Path(checkpoint_dir,'state.json').read_text())
  if state['config']!=self.config or state['trial_id']!=self.trial_id:raise RuntimeError('Checkpoint attached to different trial/configuration')
  if state['next_step']!=1:raise RuntimeError('Expected first-step interruption checkpoint')
  self.next_step=state['next_step'];self.restored_from_checkpoint=True

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--phase',choices=['start','resume'],required=True);a=p.parse_args();out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
 os.environ['PYTHONPATH']=str(pathlib.Path(__file__).resolve().parent)+os.pathsep+os.environ.get('PYTHONPATH','');os.environ['RAY_USAGE_STATS_ENABLED']='0';os.environ['CPG_ORACLES']=str(out.parent/'oracles.json');os.environ['CPG_RAY_EVIDENCE']=str(out/'trial-measurements');os.environ['TUNE_DISABLE_AUTO_CALLBACK_LOGGERS']='0'
 raytmp=tempfile.mkdtemp(prefix='cpg-e298-w83-ray-',dir='/tmp')
 try:
  ray.init(local_mode=True,num_cpus=1,include_dashboard=False,_node_ip_address="127.0.0.1",_temp_dir=raytmp,object_store_memory=90*1024*1024,log_to_driver=False)
  expt=out/'storage'/'cpg083'
  if a.phase=='start':
   t=tune.Tuner(CompileTrial,param_space={'opt':tune.grid_search([1,2,3]),'tile':8,'unroll':0,'vectorize':1},tune_config=tune.TuneConfig(metric='runtime_seconds',mode='min',max_concurrent_trials=1),run_config=RunConfig(name='cpg083',storage_path=str(out/'storage'),failure_config=FailureConfig(max_failures=0),checkpoint_config=CheckpointConfig(checkpoint_frequency=1,checkpoint_at_end=False),verbose=0))
   results=t.fit();errors=sum(r.error is not None for r in results)
   if errors!=3:raise RuntimeError(f'Expected 3 controlled interruptions, got {errors}')
   checkpoint_count=sum(r.checkpoint is not None for r in results)
   if checkpoint_count!=3:raise RuntimeError(f'All 3 trials must persist a real checkpoint, got {checkpoint_count}')
   (out/'phase1.json').write_text(json.dumps({'deliberately_interrupted_trials':errors,'checkpoint_count':sum(r.checkpoint is not None for r in results)},indent=2));print('CHECKPOINT_INTERRUPTED 3')
  else:
   if not tune.Tuner.can_restore(str(expt)):raise RuntimeError('Experiment not restorable')
   t=tune.Tuner.restore(str(expt),trainable=CompileTrial,resume_errored=True);results=t.fit()
   if len(results)!=3 or any(r.error for r in results):raise RuntimeError('Restored trials failed')
   if not all(r.metrics['restored_from_checkpoint'] and r.metrics['step']==2 for r in results):raise RuntimeError('Checkpoints were not resumed at correct step')
   measurement_rows=[]
   for path in (out/'trial-measurements').glob('*/evaluations.jsonl'):
    measurement_rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
   if len(measurement_rows)!=6 or any(not row['valid_speed'] for row in measurement_rows):raise RuntimeError('Need all six persisted real compile/execute measurements across checkpoint phases')
   for trial_id in {row['trial_id'] for row in measurement_rows}:
    owned=[row for row in measurement_rows if row['trial_id']==trial_id]
    if len(owned)!=2 or {row['phase'] for row in owned}!={'search','restored_trial'}:raise RuntimeError('Trial measurement attribution differs across restore')
   best=results.get_best_result(metric='runtime_seconds',mode='min');b=Benchmark(out,'ray-replay')
   report={'status':'passed','tool':'ray-tune','version':ray.__version__,'local_only':True,'execution_mode':'Ray local_mode=True; real Tune scheduler and persisted trial checkpoints with external measured C executables; no distributed-cluster claim','num_cpus':1,'total_trials':3,'controlled_interruptions':3,'restored_checkpoint_trials':3,'persisted_real_trial_measurements':len(measurement_rows),'best_config':best.config,'trial_results':[{'config':r.config,'runtime_seconds':r.metrics['runtime_seconds'],'restored':r.metrics['restored_from_checkpoint'],'step':r.metrics['step']} for r in results],'replay':b.replay(best.config)}
   (out/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report))
 finally:ray.shutdown();shutil.rmtree(raytmp,ignore_errors=True)
