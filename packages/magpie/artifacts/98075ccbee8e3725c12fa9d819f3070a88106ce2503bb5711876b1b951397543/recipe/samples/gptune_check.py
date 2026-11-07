import ctypes, json, math, os, pathlib, sys
import numpy as np
from autotune.space import Space, Real, Integer
from autotune.problem import TuningProblem
from GPTune.gptune import GPTune, Computer, Options, Data, HistoryDB

R=pathlib.Path(__file__).resolve().parents[1]
lib=ctypes.CDLL(str(R/'build/libcpg_kernel.so'))
lib.cpg_measure.argtypes=[ctypes.c_int]*4+[ctypes.POINTER(ctypes.c_uint64)]
lib.cpg_measure.restype=ctypes.c_double
calls=[]
def require(c,m):
    if not c:raise RuntimeError(m)
def objective(p):
    task=float(p['task']);exponent=int(p['exponent'])
    n=int(round(task*65536));block=2**exponent
    require(n%block==0,'unsupported task/configuration passed to kernel')
    checksum=ctypes.c_uint64()
    seconds=lib.cpg_measure(block,1,n,60,ctypes.byref(checksum))
    require(seconds>0 and math.isfinite(seconds),'kernel correctness/timing failed')
    calls.append(dict(task=task,exponent=exponent,n=n,block=block,seconds=seconds,checksum=checksum.value,correct=True))
    # GPTune's native history rounds objective values to six decimal places.
    # Microseconds preserve sub-microsecond resolution without patching upstream.
    return [seconds * 1e6]

IS=Space([Real(1.0,2.0,transform='normalize',name='task')])
PS=Space([Integer(4,9,transform='normalize',name='exponent')])
OS=Space([Real(0.0,float('inf'),name='microseconds')])
problem=TuningProblem(IS,PS,OS,objective,{'valid_exponent':'exponent >= 4 and exponent <= 9'},None)
computer=Computer(nodes=1,cores=2,hosts=None)
options=Options()
options.update(lite_mode=True,model_class='Model_GPy_LCM',search_class='SearchSciPy',search_algo='dual_annealing',
    distributed_memory_parallelism=False,shared_memory_parallelism=False,model_restarts=1,
    model_threads=1,model_processes=1,model_max_iters=40,search_max_iters=5,
    sample_class='SampleLHSMDU',sample_random_seed=84,model_random_seed=84,search_random_seed=84,
    verbose=False)
options.validate(computer=computer)
dbpath=pathlib.Path.cwd()/'gptune-history'
dbpath.mkdir(exist_ok=True)
meta={'tuning_problem_name':'cpg-worker084-cpu-block','historydb_path':str(dbpath),
    'sync_crowd_repo':'no','save_model':'no','load_func_eval':'yes',
    'machine_configuration':{'machine_name':'cpg-validation','cpu':{'nodes':1,'cores':2}},
    'software_configuration':{},
    'loadable_machine_configurations':{'cpg-validation':{'cpu':{'nodes':1,'cores':2}}},
    'loadable_software_configurations':{}}
def tuner():
    return GPTune(problem,computer=computer,data=Data(problem),options=options,
                  historydb=HistoryDB(meta_dict=meta),driverabspath=str(pathlib.Path(__file__).resolve()))
gt=tuner()
lite,_,s1=gt.MLA(NS=4,NS1=2,NI=1,Tgiven=[[1.0]])
require(len(lite.P[0])==4,'lite budget mismatch')
lite_calls=len(calls)
gt2=tuner()
data,_,s2=gt2.MLA(NS=5,NS1=2,NI=2,Tgiven=[[1.0],[2.0]])
require(len(data.P)==2 and all(len(x)==5 for x in data.P),'multi-task budget mismatch')
history=json.loads((dbpath/'cpg-worker084-cpu-block.json').read_text())
func=history['func_eval']
task_counts={}
for row in func:
    key=str(float(row['task_parameter']['task']))
    task_counts[key]=task_counts.get(key,0)+1
require(task_counts=={'1.0':5,'2.0':5},'history task ownership mismatch')
require(len({x['uid'] for x in func})==10,'duplicate history UID')
before=len(calls)
restored,_,s3=tuner().MLA(NS=5,NS1=2,NI=2,Tgiven=[[1.0],[2.0]])
require(len(calls)==before,'history restoration reevaluated existing samples')
for i in range(2):
    require(np.array_equal(restored.P[i],data.P[i]),'restored configurations changed')
    require(np.array_equal(restored.O[i],np.round(data.O[i],6)),
            'restored measurements differ from native six-decimal serialization')
# Native GPTune TLA_II transfers optimum information from two measured tasks.
transfer=tuner()
params,values,transfer_stats=transfer.TLA_II(Tnew=[[1.5]],Tsrc=[[1.0],[2.0]])
require(len(params)==1 and len(values)==1,'transfer did not execute target task')
require(calls[-1]['task']==1.5,'transferred measurement lost task identity')
replays=[]
for i,t in enumerate([1.0,2.0]):
    k=int(np.argmin(data.O[i]))
    p=int(data.P[i][k][0]);replayed=objective({'task':t,'exponent':p})[0]
    replays.append({'task':t,'exponent':p,'training_microseconds':float(data.O[i][k][0]),'replay_microseconds':replayed,'correct':True})
report={'status':'pass','backend':'native_cpu','mode':'GPTune lite with GPy and SciPy; no MPI',
    'lite_measurements':lite_calls,'training_tasks':[1.0,2.0],'history_task_counts':task_counts,
    'history_restore_without_evaluation':True,'history_rounding_decimal_places':6,
    'objective_unit':'microseconds_per_repetition','repetitions':60,
    'transfer_api':'TLA_II','transfer_target_task':1.5,
    'transfer_parameters':params,'transfer_results':[x.tolist() for x in values],
    'best_replays':replays,'calls':calls,'gpu_executed':False}
pathlib.Path('gptune-result.json').write_text(json.dumps(report,indent=2,default=lambda x:x.tolist() if hasattr(x,'tolist') else str(x))+'\n')
print(json.dumps(report,default=str))
