#!/usr/bin/env python3
import argparse, hashlib, json, pathlib, shutil, subprocess, sys, tarfile, tempfile
p=argparse.ArgumentParser()
p.add_argument('--resource',required=True)
p.add_argument('--prefix',type=pathlib.Path,required=True)
p.add_argument('--build',type=pathlib.Path,required=True)
a=p.parse_args()
a.prefix=a.prefix.resolve()
a.build.mkdir(parents=True,exist_ok=True)
work=pathlib.Path(tempfile.mkdtemp(prefix=a.resource+'-check-',dir=a.build))
for row in json.loads((a.prefix/'metadata/source-locks.json').read_text()):
    q=a.prefix/'raw'/row['filename']
    if q.stat().st_size!=row['bytes'] or hashlib.sha256(q.read_bytes()).hexdigest()!=row['sha256']:
        raise SystemExit('source identity mismatch: '+row['name'])
prefix=a.prefix
if a.resource=='bpftool':
    # EM_BPF objects are target data, not native host executables. They remain
    # archived in the installed prefix and are opened only by this offline check.
    prefix=work/'fixture-view'
    (prefix/'bin').mkdir(parents=True)
    (prefix/'tests/bpf').mkdir(parents=True)
    for name in ['bpftool','skeleton-probe']:
        shutil.copy2(a.prefix/'bin'/name,prefix/'bin'/name)
    with tarfile.open(a.prefix/'data/bpf-fixtures.tar.gz') as tf:
        tf.extractall(prefix/'tests/bpf',filter='data')
driver=pathlib.Path(__file__).with_name('worker014.py')
cmd=[sys.executable,str(driver),'check','--resource',a.resource,'--prefix',str(prefix),'--report',str(work/'report')]
result=subprocess.run(cmd)
raise SystemExit(result.returncode)
