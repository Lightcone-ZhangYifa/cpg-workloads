import argparse,json,pathlib,time
from benchmark import Benchmark,DEFAULT
p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--evidence',required=True);p.add_argument('--oracles',required=True);p.add_argument('--token',required=True);p.add_argument('--delay',type=float,default=0);a=p.parse_args()
c=json.loads(a.config);mode=c.pop('mode');c.update(opt=int(mode[1]),unroll=int('unroll' in mode))
# This delay tests out-of-order completion and is excluded from measured C runtime.
time.sleep(a.delay)
v=Benchmark(a.evidence,'ytopt',a.oracles).evaluate(c,trial_id=a.token)
print(json.dumps({'token':a.token,'configuration':json.loads(a.config),'runtime_seconds':v,'compiled_configuration':c}))
