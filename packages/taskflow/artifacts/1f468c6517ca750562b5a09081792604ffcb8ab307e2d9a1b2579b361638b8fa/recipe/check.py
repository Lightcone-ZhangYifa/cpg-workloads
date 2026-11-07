#!/usr/bin/env python3
"""Independent integer serial oracle for actual Taskflow dependent task graphs."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def expected(seed):
    rows = []
    for n in (0, 1, 17, 257):
        xs = [((i * 37 + seed * 11) % 251) - 125 for i in range(n)]
        rows.append(dict(scenario='dag', n=n, counts=[7]*4,
                         result=[x*x-2*x+18 for x in xs]))
    for choice in (0, 1, 2, 9):
        values = [seed*seed+1, seed*3-7, seed+23]
        rows.append(dict(scenario='branch', selection=choice,
                         hits=[7 if i == choice else 0 for i in range(3)],
                         result=values[choice] if choice < 3 else -999))
    for n in (1, 2, 17, 257):
        rows.append(dict(scenario='loop', limit=n, iterations=n, stops=3,
                         result=seed+sum((i*7+seed)%97 for i in range(1, n+1))))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prefix', required=True, type=Path)
    ap.add_argument('--work', required=True, type=Path)
    ap.add_argument('--cxx', default=os.environ.get('CXX', 'g++'))
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    recipe = Path(__file__).resolve().parent
    exe = args.work / 'taskflow-consumer'
    compile_argv = [args.cxx, '-std=c++20', '-O2', '-pthread', '-I'+str(args.prefix/'include'),
                    str(recipe/'consumer.cpp'), '-o', str(exe)]
    cp = subprocess.run(compile_argv, capture_output=True, text=True, timeout=180)
    records = [{'phase':'compile', 'argv':compile_argv, 'returncode':cp.returncode,
                'stdout':cp.stdout, 'stderr':cp.stderr}]
    if cp.returncode:
        (args.work/'result.json').write_text(json.dumps({'status':'failed','records':records},indent=2)+'\n')
        raise SystemExit('Taskflow consumer compilation failed')
    for workers in (1, 2, 4):
        for seed in (0, 7, 65535):
            argv = [str(exe), str(workers), str(seed)]
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            actual = [json.loads(line) for line in cp.stdout.splitlines()] if cp.returncode == 0 else None
            ok = cp.returncode == 0 and actual == expected(seed)
            records.append({'phase':'execute', 'workers':workers, 'seed':seed, 'passed':ok,
                            'returncode':cp.returncode, 'stdout':cp.stdout, 'stderr':cp.stderr})
            if not ok:
                (args.work/'result.json').write_text(json.dumps({'status':'failed','records':records},indent=2)+'\n')
                raise SystemExit('Taskflow output differs from independent serial oracle')
    cp = subprocess.run([str(exe),'2','7','mutate'],capture_output=True,text=True,timeout=30)
    mutation_rejected = cp.returncode == 0 and [json.loads(x) for x in cp.stdout.splitlines()] != expected(7)
    records.append({'phase':'negative_oracle','passed':mutation_rejected,'stdout':cp.stdout,'stderr':cp.stderr})
    cp = subprocess.run([str(exe),'0','7'],capture_output=True,text=True,timeout=30)
    invalid_rejected = cp.returncode == 2
    records.append({'phase':'invalid_workers','passed':invalid_rejected,'returncode':cp.returncode,'stderr':cp.stderr})
    if not (mutation_rejected and invalid_rejected):
        raise SystemExit('negative controls failed')
    result = dict(status='passed', scenario_cases=108, serial_oracle='independent Python integer expressions',
                  scope='CPU dependency DAG, selected/out-of-range condition edges and self-loop; no GPU or performance claim',
                  negative_controls=2, records=records)
    (args.work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','scenario_cases':108,'negative_controls':2,'marker':'TASKFLOW_FUNCTIONAL_OK'}))


if __name__ == '__main__':
    main()
