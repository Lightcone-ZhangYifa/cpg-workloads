#!/usr/bin/env python3
"""Build a fixed OpenBLAS BLAS/CBLAS profile and execute pinned upstream tests."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','build','prefix'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--jobs',type=int,required=True);args=p.parse_args()
    if not 1<=args.jobs<=2:raise RuntimeError('At most two compiler jobs are permitted')
    config=json.loads(Path(__file__).with_name('config.json').read_text())
    flags=config['make_flags']; source=args.source.resolve(); build=args.build/'openblas'
    if build.exists():raise RuntimeError('Fresh build directory is required')
    shutil.copytree(source,build,symlinks=True)
    evidence=args.prefix/'share/compiler-playground/openblas';evidence.mkdir(parents=True)
    env=dict(os.environ,LC_ALL='C',PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    for name in ('LD_PRELOAD','LD_LIBRARY_PATH','LIBRARY_PATH','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH',
                 'CFLAGS','CXXFLAGS','LDFLAGS','MAKEFLAGS','MFLAGS','OPENBLAS_CORETYPE'):
        env.pop(name,None)
    commands=[]
    def run(label,argv,*,cwd=build,input_file=None,timeout=1800):
        argv=list(map(str,argv));print(json.dumps({'label':label,'argv':argv}),flush=True)
        input_text=input_file.read_text() if input_file else None
        with (evidence/(label+'.stdout')).open('w') as out,(evidence/(label+'.stderr')).open('w') as err:
            result=subprocess.run(argv,cwd=cwd,env=env,input=input_text,text=True,stdout=out,stderr=err,timeout=timeout)
        row={'label':label,'argv':argv,'cwd':str(cwd),'returncode':result.returncode,'stdout':label+'.stdout','stderr':label+'.stderr'}
        if input_file:row['input']={'path':str(input_file),'sha256':sha(input_file),'bytes':input_file.stat().st_size}
        commands.append(row);(evidence/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if result.returncode:raise RuntimeError('Actual upstream command failed: '+label)
        return (evidence/(label+'.stdout')).read_text()
    make=['/usr/bin/make','-j'+str(args.jobs),*flags]
    run('build-shared-static',make+['shared'],timeout=2400)
    unit_names=['openblas_utest','openblas_utest_ext']
    run('build-upstream-unit',make+['-C','utest',*unit_names],timeout=600)
    blas_names=['x'+kind+'cblat'+str(level) for kind in 'sdcz' for level in (1,2,3)]
    run('build-upstream-cblas',make+['-C','ctest',*blas_names],timeout=600)
    upstream={'unit_executables':[],'cblas_executables':[],'unknown_selector_negative':[]}
    for name in unit_names:
        executable=build/'utest'/name
        empty=run(name+'-unknown-selector',[executable,'cpg_nonexistent_suite'],cwd=build/'utest',timeout=60)
        if not re.search(r'RESULTS: 0 tests \(0 ok, 0 failed, 0 skipped\)',empty) or re.search(r'^TEST ',empty,re.M):
            raise RuntimeError('Unknown upstream selector did not run zero tests')
        upstream['unknown_selector_negative'].append({'executable':name,'executed_tests':0})
        stdout=run('upstream-'+name,[executable],cwd=build/'utest',timeout=300)
        text=re.sub(r'\x1b\[[0-9;]*m','',stdout)
        summaries=re.findall(r'RESULTS: (\d+) tests \((\d+) ok, (\d+) failed, (\d+) skipped\)',text)
        cases=re.findall(r'^TEST (\d+)/(\d+) (\S+) \[(OK|SKIPPED|FAIL)\]',text,re.M)
        if len(summaries)!=1:raise RuntimeError('Missing unique actual unit-test summary')
        total,passed,failed,skipped=map(int,summaries[0])
        if total==0 or passed==0 or failed or len(cases)!=total or passed+skipped!=total:
            raise RuntimeError('Upstream test execution was empty, failed, or incompletely accounted')
        if [int(x[0]) for x in cases]!=list(range(1,total+1)) or any(int(x[1])!=total for x in cases):
            raise RuntimeError('Upstream sequence incomplete')
        statuses=Counter(x[3] for x in cases)
        if statuses!=Counter({'OK':passed,'SKIPPED':skipped,'FAIL':failed}):
            raise RuntimeError('Per-case statuses disagree with upstream summary')
        upstream['unit_executables'].append({'name':name,'sha256':sha(executable),'planned':total,'passed':passed,
            'failed':failed,'skipped':skipped,'cases':[{'name':x[2],'status':x[3]} for x in cases]})
    for kind in 'sdcz':
        for level in (1,2,3):
            name='x'+kind+'cblat'+str(level);executable=build/'ctest'/name
            input_file=source/'ctest'/(kind+'in'+str(level)) if level>1 else None
            stdout=run('upstream-'+name,[executable],cwd=build/'ctest',input_file=input_file,timeout=300)
            stderr=(evidence/('upstream-'+name+'.stderr')).read_text()
            if re.search(r'FAIL|FATAL|ABANDONED|SUSPECT|Shouldn.t be here',stdout+stderr,re.I):
                raise RuntimeError('Upstream BLAS oracle reported failure despite process status: '+name)
            row={'name':name,'sha256':sha(executable),'level':level,'status':'passed'}
            if level==1:
                expected=11 if kind in 'sd' else 10
                names=re.findall(r'Test of subprogram number\s+\d+\s+(\S+)',stdout)
                passed=len(re.findall(r'----- PASS -----',stdout))
                if passed!=expected or len(names)!=expected:raise RuntimeError('Incomplete BLAS1 subprogram execution')
                row.update(subprograms=names,passed_subprograms=passed)
            else:
                expected_names=re.findall(r'^(cblas_\w+)\s+T\b',input_file.read_text(),re.M)
                computational=re.findall(r'(cblas_\w+)\s+PASSED THE (?:(COLUMN|ROW)-MAJOR )?COMPUTATIONAL TESTS\s*\(\s*(\d+) CALLS\)',stdout)
                expected={(name,layout) for name in expected_names for layout in ('COLUMN','ROW')}
                explicit=all(x[1] for x in computational)
                valid_groups=({(x[0],x[1]) for x in computational}==expected if explicit else
                    all(not x[1] for x in computational) and kind in 'cz' and
                    Counter(x[0] for x in computational)==Counter({name:2 for name in expected_names}))
                if not valid_groups or len(computational)!=len(expected) or any(int(x[2])<=0 for x in computational):
                    raise RuntimeError('Incomplete actual BLAS computation matrix: '+name)
                if 'END OF TESTS' not in stdout or 'ERROR-EXITS WILL NOT BE TESTED' in stdout or 'COLUMN-MAJOR AND ROW-MAJOR DATA LAYOUTS ARE TESTED' not in stdout:
                    raise RuntimeError('BLAS tests did not finish the declared error-exit profile')
                error_names=re.findall(r'(cblas_\w+)\s+PASSED THE TESTS OF ERROR-EXITS',stdout)
                expected_errors=Counter(expected_names)
                gaps=[]
                if kind in 'cz' and level==2:
                    # Upstream strncmp(...,10) routes gerc to geru in error-exit
                    # tests only. Preserve the duplicate geru label and report
                    # the unexecuted gerc branch; do not relabel it as coverage.
                    gerc='cblas_'+kind+'gerc';geru='cblas_'+kind+'geru'
                    expected_errors[gerc]-=1;expected_errors[geru]+=1
                    gaps=[{'not_executed_upstream':gerc,'duplicated_upstream':geru,
                           'cause':'ctest/c_'+kind+'2chke.c strncmp length 10 selects the earlier geru branch',
                           'project_negative_control':'Separate installed C consumer invokes gerc with invalid lda and verifies XERBLA parameter 9.'}]
                if Counter(error_names)!=expected_errors:
                    raise RuntimeError('Error-exit execution records differ from fixed upstream control flow')
                row.update(selected_subprograms=expected_names,passed_layout_groups=len(computational),
                    computational_calls=sum(int(x[2]) for x in computational),
                    layout_groups=[{'subprogram':x[0],'layout':x[1] or 'not_printed_by_upstream','calls':int(x[2])} for x in computational],
                    layout_evidence='Explicit labels' if explicit else 'Original mode=2 fixture and two source-control-flow invocations; actual output omits per-call layout labels',
                    input_sha256=sha(input_file),error_exit_tests_enabled=True,
                    error_exit_pass_records=error_names,known_upstream_error_exit_gaps=gaps)
            upstream['cblas_executables'].append(row)
    run('install',make+['PREFIX='+str(args.prefix),'install'],timeout=180)
    # All original members remain unmodified in a separate retained material view.
    shutil.copytree(source,args.prefix/'share/openblas/source',symlinks=True)
    for name in ('build.py','check.py','config.json','consumer.c'):
        shutil.copy2(Path(__file__).with_name(name),evidence/name)
    run('build-probe',['/usr/bin/gcc','-std=c11','-O2','-g0','-I'+str(args.prefix/'include'),
        Path(__file__).with_name('consumer.c'),args.prefix/'lib/libopenblas.so','-Wl,-rpath,$ORIGIN/../lib',
        '-lm','-pthread','-o',args.prefix/'bin/openblas-cpg-probe'],timeout=120)
    profile={'schema_version':1,'id':'openblas','version':'0.3.34','source_modified':False,
        'configuration':config['configuration'],'make_flags':flags,
        'build_budget':{'maximum_jobs':2,'actual_jobs':args.jobs,'compiler_timeout_seconds':2400,'build_cache':'fresh copied source; no reused objects'},
        'upstream_tests':upstream,'unperformed':config['unperformed'],
        'relocation_scope':'Explicit-prefix C consumers and the project probe on the observed Ubuntu 24.04 x86_64 ABI. Upstream generated absolute-path CMake/pkg-config metadata is not qualified for relocation.'}
    (evidence/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')


if __name__=='__main__':main()
