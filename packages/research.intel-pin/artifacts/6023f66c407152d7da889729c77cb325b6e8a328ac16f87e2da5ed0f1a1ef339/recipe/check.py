#!/usr/bin/env python3
"""Fresh output directory per invocation; never accepts an earlier result."""
import argparse, json, pathlib, subprocess, sys, uuid

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--build',required=True);ap.add_argument('--recipe',required=True);args=ap.parse_args()
    recipe=pathlib.Path(args.recipe).resolve();cfg=json.loads((recipe/'config.json').read_text());kind=cfg['kind']
    parent=pathlib.Path(args.build).resolve()/'semantic-checks';parent.mkdir(parents=True,exist_ok=True)
    work=parent/uuid.uuid4().hex
    if kind=='intel-pin':argv=[sys.executable,'-B',str(recipe/'check_pin.py'),'--kit',str(pathlib.Path(args.prefix)/'kit'),'--client',str(pathlib.Path(args.prefix)/'client/inscount0.so'),'--out',str(work)]
    else:argv=[sys.executable,'-B',str(recipe/'functional.py'),kind,args.prefix,str(work)]
    completed=subprocess.run(argv)
    if completed.returncode:raise SystemExit(completed.returncode)
    result=json.loads((work/'result.json').read_text())
    if result.get('status')!='passed':raise RuntimeError('current semantic result is not passed')
    print('CPG074_FUNCTIONAL_PASSED '+json.dumps({'kind':kind,'result':str(work/'result.json')}))

if __name__=='__main__':main()
