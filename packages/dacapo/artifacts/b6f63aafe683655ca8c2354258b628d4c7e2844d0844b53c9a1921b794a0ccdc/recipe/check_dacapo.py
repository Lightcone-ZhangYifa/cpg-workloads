"""Run bounded official DaCapo workloads with the suite's own validation enabled."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

def validate_output(text,benchmark):
    version='DaCapo 9.12-MR1'
    passed=re.findall(r'===== '+re.escape(version)+' '+re.escape(benchmark)+r' PASSED in (\d+) msec =====',text)
    warmup=re.findall(r'===== '+re.escape(version)+' '+re.escape(benchmark)+r' completed warmup 1 in (\d+) msec =====',text)
    assert len(passed)==1 and len(warmup)==1,(benchmark,text[-4000:])
    assert 'FAILED' not in text and 'Validation FAILED' not in text
    return {'benchmark':benchmark,'warmup_milliseconds':int(warmup[0]),'elapsed_milliseconds':int(passed[0])}

def check(prefix,toolchain,out):
    out.mkdir(parents=True,exist_ok=True)
    jar=prefix/'dacapo-9.12-MR1-bach.jar'
    with jar.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()=='be3db084adcb2867760e1197b3ccf541c3213d918daa19386d8e236648d24be8'
    results=[]
    environment=dict(os.environ,LD_LIBRARY_PATH=str(toolchain/'native/usr/lib/x86_64-linux-gnu')+':'+str(toolchain/'jdk/lib')+':'+str(toolchain/'jdk/lib/server'))
    with tempfile.TemporaryDirectory(prefix='cpg-dacapo-') as temporary:
        work=Path(temporary)
        for benchmark in ('avrora','fop','luindex'):
            argv=[str(toolchain/'jdk/bin/java'),'-Xmx512m','-Djava.awt.headless=true','-jar',str(jar),'-s','small','-n','2','-t','1','--scratch-directory',str(work/benchmark),benchmark]
            started=time.monotonic();p=subprocess.run(argv,cwd=work,env=environment,capture_output=True,text=True,timeout=180)
            (out/(benchmark+'.stdout.log')).write_text(p.stdout);(out/(benchmark+'.stderr.log')).write_text(p.stderr)
            (out/(benchmark+'.command.json')).write_text(json.dumps({'argv':argv,'returncode':p.returncode,'elapsed_seconds':time.monotonic()-started},indent=2))
            assert p.returncode==0,(benchmark,p.returncode,p.stderr[-2000:])
            output=p.stdout+p.stderr;results.append(validate_output(output,benchmark))
            try:validate_output(output.replace(' PASSED in ',' FAILED in '),benchmark)
            except AssertionError:pass
            else:raise AssertionError('Oracle accepted failed validation')
        argv=[str(toolchain/'jdk/bin/java'),'-Xmx128m','-jar',str(jar),'cpg-invalid-benchmark']
        p=subprocess.run(argv,cwd=work,env=environment,capture_output=True,text=True,timeout=30)
        (out/'invalid-benchmark.stdout.log').write_text(p.stdout);(out/'invalid-benchmark.stderr.log').write_text(p.stderr)
        assert p.returncode!=0
    summary={'status':'passed','suite':'9.12-MR1-bach','suite_sha256':'be3db084adcb2867760e1197b3ccf541c3213d918daa19386d8e236648d24be8','jdk_version':'17.0.21+9','size':'small','iterations':2,'threads':1,'validation_enabled':True,'selected_benchmarks':results,'negative_controls':['invalid benchmark rejected','FAILED output rejected for each selected workload'],'scope':'Three bounded functional workloads from the complete official binary suite. No all-suite score or source build is claimed.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,sort_keys=True))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',type=Path,required=True);ap.add_argument('--toolchain',type=Path,required=True);ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    if args.output:check(args.prefix.resolve(),args.toolchain.resolve(),args.output.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='cpg-dacapo-evidence-') as out:check(args.prefix.resolve(),args.toolchain.resolve(),Path(out))
