import ctypes, json, math, pathlib, sys
from pyatf import TP, Set, Tuner
from pyatf.abort_conditions import Evaluations
from pyatf.search_techniques import Exhaustive

root=pathlib.Path(__file__).resolve().parents[1]
lib=ctypes.CDLL(str(root/'build/libcpg_kernel.so'))
lib.cpg_measure.argtypes=[ctypes.c_int]*4+[ctypes.POINTER(ctypes.c_uint64)]
lib.cpg_measure.restype=ctypes.c_double
n=131072
trials=[]
def require(condition, message):
    if not condition:
        raise RuntimeError(message)
def cost(config):
    b,u=config['block'],config['unroll']
    require(n%b==0 and b%u==0 and u<=b, 'invalid configuration reached actual kernel')
    checksum=ctypes.c_uint64()
    seconds=lib.cpg_measure(b,u,n,60,ctypes.byref(checksum))
    require(seconds>0 and math.isfinite(seconds), 'kernel execution or correctness failed')
    trials.append(dict(config,seconds=seconds,checksum=checksum.value,correct=True))
    return seconds

block=TP('block',Set(16,32,64,128,192),lambda block:n%block==0)
unroll=TP('unroll',Set(1,2,3,4,8),lambda block,unroll:unroll<=block and block%unroll==0)
tuner=Tuner().tuning_parameters(block,unroll).search_technique(Exhaustive()).verbosity(0).log_file('pyatf-upstream.json')
best,value,data=tuner.tune(cost,Evaluations(16))
require(len(trials)==16 and len({(x['block'],x['unroll']) for x in trials})==16, 'budget or unique coverage mismatch')
require(data.number_of_evaluated_valid_configurations==16, 'valid configuration count mismatch')
history=trials.copy()
require(value==min(x['seconds'] for x in history), 'selected cost is not measured minimum')
replay=cost(best)
bad=ctypes.c_uint64()
require(lib.cpg_measure(192,3,n,1,ctypes.byref(bad))==-1, 'invalid config not rejected')
pathlib.Path('pyatf-trials.json').write_text(json.dumps(history,indent=2)+'\n')
result=dict(status='pass',backend='native_cpu',evaluated=16,unique_configs=16,budget=16,repetitions=60,time_unit="seconds_per_repetition",
            constraint_rejected_count=9,invalid_executed=0,best=best,best_seconds=value,
            replay_seconds=replay,correctness=True,negative_invalid_config_rejected=True)
pathlib.Path('pyatf-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
