import sys,pathlib,json,os
from benchmark import Benchmark
# irace supplies fixed configuration/instance/seed, then exact parameter switches.
a=sys.argv[1:];trial,instance,seed=a[:3];pairs=dict(zip(a[3::2],a[4::2]));cfg={'opt':int(pairs['--opt']),'tile':int(pairs['--tile']),'unroll':int(pairs.get('--unroll','0')),'vectorize':int(pairs['--vectorize'])}
out=pathlib.Path(os.environ['CPG083_IRACE_OUTPUT'])
v=Benchmark(out,'irace').evaluate(cfg,instance,repeats=1,trial_id={'configuration':trial,'irace_seed':seed})
print(v)
