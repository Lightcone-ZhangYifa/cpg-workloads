"""Rebuild a real JMH benchmark offline, check output, forks, and negative controls."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

def execute(argv, cwd, env, out, label, expected=0):
    started=time.monotonic()
    p=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,capture_output=True,text=True,timeout=180)
    (out/(label+'.stdout.log')).write_text(p.stdout)
    (out/(label+'.stderr.log')).write_text(p.stderr)
    (out/(label+'.command.json')).write_text(json.dumps({'argv':[str(x) for x in argv],'returncode':p.returncode,'elapsed_seconds':time.monotonic()-started},indent=2))
    if expected is not None and p.returncode!=expected:raise AssertionError((label,p.returncode,p.stderr[-2000:]))
    return p

def validate_results(rows):
    assert isinstance(rows,list) and len(rows)==2
    assert {r['params']['length'] for r in rows}=={'1024','8192'}
    for row in rows:
        assert row['jmhVersion']=='1.37'
        assert row['benchmark']=='cpg.bench.SumBenchmark.sumArray'
        assert row['mode']=='avgt' and row['threads']==1
        assert row['forks']==2 and row['warmupIterations']==1 and row['measurementIterations']==2
        assert row['warmupTime']=='100 ms' and row['measurementTime']=='100 ms'
        metric=row['primaryMetric']
        assert metric['scoreUnit']=='ns/op' and math.isfinite(metric['score']) and metric['score']>0
        assert len(metric['rawData'])==2 and all(len(fork)==2 for fork in metric['rawData'])

def validate_checksum(text):
    seen={}
    for line in text.strip().splitlines():
        length,value=map(int,line.split(':'));seen[length]=value
    expected={n:sum((i*17+3)&65535 for i in range(n)) for n in (1024,8192)}
    assert seen==expected,(seen,expected)
    return expected

def check(prefix,toolchain,out):
    out.mkdir(parents=True,exist_ok=True)
    lock=json.loads((prefix/'maven-lock.json').read_text())
    for row in lock['entries']:
        path=prefix/'maven-repository'/row['path']
        with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        assert path.stat().st_size==row['bytes'] and digest==row['sha256'],row['path']
    with tempfile.TemporaryDirectory(prefix='cpg-jmh-') as temporary:
        work=Path(temporary)
        shutil.copytree(prefix/'project',work/'project')
        shutil.copytree(prefix/'maven-repository',work/'repository')
        env=dict(os.environ,JAVA_HOME=str(toolchain/'jdk'),MAVEN_OPTS='-Xmx256m',MAVEN_SKIP_RC='true')
        env['LD_LIBRARY_PATH']=str(toolchain/'native/usr/lib/x86_64-linux-gnu')+':'+str(toolchain/'jdk/lib')+':'+str(toolchain/'jdk/lib/server')
        env['PATH']=str(toolchain/'jdk/bin')+os.pathsep+env.get('PATH',os.defpath)
        java=toolchain/'jdk/bin/java'
        mvn=[toolchain/'maven/bin/mvn','-o','-B','-ntp','-Dmaven.repo.local='+str(work/'repository')]
        execute([java,'-version'],work,env,out,'jdk')
        execute(mvn+['clean','package'],work/'project',env,out,'offline-build')
        jar=work/'project/target/benchmarks.jar'
        assert jar.is_file()
        with jar.open('rb') as stream: compiled_jar_sha256=hashlib.file_digest(stream,'sha256').hexdigest()
        checksum=execute([java,'-Xmx128m','-cp',jar,'cpg.bench.CorrectnessMain','1024','8192'],work,env,out,'checksum')
        expected=validate_checksum(checksum.stdout)
        result=out/'jmh-results.json'
        execute([java,'-Xmx256m','-jar',jar,'cpg.bench.SumBenchmark.sumArray','-wi','1','-w','100ms','-i','2','-r','100ms','-f','2','-t','1','-jvmArgs','-Xmx256m','-rf','json','-rff',result,'-foe','true'],work,env,out,'jmh')
        rows=json.loads(result.read_text());validate_results(rows)
        negative=execute([java,'-Xmx128m','-jar',jar,'NoSuchBenchmark_RegressionControl','-f','0'],work,env,out,'unknown-benchmark',expected=None)
        assert negative.returncode!=0 and 'No matching benchmarks' in negative.stdout+negative.stderr
        altered=json.loads(result.read_text());altered[0]['forks']=0
        try:validate_results(altered)
        except AssertionError:pass
        else:raise AssertionError('Protocol oracle accepted incorrect fork metadata')
        source=work/'project/src/main/java/cpg/bench/SumBenchmark.java'
        original=source.read_text();assert 'total += value;' in original
        source.write_text(original.replace('total += value;','total += value + 1;'))
        execute(mvn+['package'],work/'project',env,out,'negative-mutant-build')
        mutant=execute([java,'-Xmx128m','-cp',jar,'cpg.bench.CorrectnessMain','1024','8192'],work,env,out,'negative-mutant-output')
        try:validate_checksum(mutant.stdout)
        except AssertionError:pass
        else:raise AssertionError('Correctness oracle accepted wrong executable output')
    summary={'status':'passed','jmh_version':'1.37','jdk_version':'17.0.21+9','maven_version':'3.9.9','source_rebuild':'offline','compiled_jar_sha256':compiled_jar_sha256,'benchmark_cases':2,'forks_per_case':2,'measurement_iterations_per_fork':2,'checksums':expected,'blackhole':True,'state':'Scope.Thread','negative_controls':['unknown benchmark rejected','incorrect fork metadata rejected','compiled wrong-output mutant rejected'],'scope':'Harness functionality and output correctness only. Short timings are not optimization or application-performance evidence.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,sort_keys=True))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',type=Path,required=True);ap.add_argument('--toolchain',type=Path,required=True);ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    if args.output:check(args.prefix.resolve(),args.toolchain.resolve(),args.output.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='cpg-jmh-evidence-') as out:check(args.prefix.resolve(),args.toolchain.resolve(),Path(out))
