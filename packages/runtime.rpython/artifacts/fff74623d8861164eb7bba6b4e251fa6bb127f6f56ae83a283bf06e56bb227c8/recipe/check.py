import argparse,pathlib,subprocess,sys
p=argparse.ArgumentParser();p.add_argument("--prefix",required=True);a=p.parse_args()
args=['python3', '-I', '-B', '{prefix}/check.py', '--prefix', '{prefix}']
args=[s.replace("{prefix}",str(pathlib.Path(a.prefix).resolve())) for s in args]
r=subprocess.run(args)
raise SystemExit(r.returncode)
