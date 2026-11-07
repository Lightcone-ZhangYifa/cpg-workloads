import argparse,csv,json,pathlib
from benchmark import Benchmark
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=pathlib.Path(a.out).resolve();b=Benchmark(out,'irace-replay');rows=list(csv.DictReader((out/'elite.csv').open()))
if not rows:raise RuntimeError('No irace elite configurations')
training=[json.loads(x) for x in (out/'evaluations.jsonl').read_text().splitlines() if json.loads(x)['phase']=='search']
train_ids=sorted(set(r['instance'] for r in training));test_ids=b.oracles['heldout_instances']
if not 1 <= len(training) <= 128:raise RuntimeError('irace exceeded measured budget')
if len(train_ids)<2 or set(train_ids)-set(b.oracles['train_instances']) or set(train_ids)&set(test_ids):raise RuntimeError('Training/evaluation separation failed')
if not all(r['valid_speed'] and r['status']=='ok' for r in training):raise RuntimeError('Failed target was counted as measured runtime')
replay=[]
for row in rows:
 cfg={k:int(row[k] or 0) for k in ['opt','tile','unroll','vectorize']};replay.append(b.replay(cfg))
report={'status':'passed','tool':'irace','version':(out/'version.txt').read_text().strip(),'seed':83,'budget':128,'actual_training_evaluations':len(training),'training_instances':train_ids,'heldout_instances':test_ids,'train_test_disjoint':True,'elite_count':len(rows),'best_config':replay[0]['config'],'elite_replays':replay,'primary_objective':'actual C kernel runtime only','irace_saved_state':'irace.Rdata'}
(out/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report))
