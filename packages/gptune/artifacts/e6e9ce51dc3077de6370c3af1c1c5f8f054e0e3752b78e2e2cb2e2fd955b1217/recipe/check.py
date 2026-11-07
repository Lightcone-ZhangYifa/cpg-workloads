"""Functional checks run real upstream tools in new external work directories."""
import argparse, json, os, pathlib, re, subprocess, sys, tempfile

def require(value,message):
    if not value:raise RuntimeError(message)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--work',required=True);a=ap.parse_args()
    p=pathlib.Path(a.prefix).resolve();base=pathlib.Path(a.work).resolve();base.mkdir(parents=True,exist_ok=True)
    require(p!=base and p not in base.parents,'checks must not write into the installed prefix')
    w=pathlib.Path(tempfile.mkdtemp(prefix='functional-',dir=base));cfg=json.loads((p/'profile.json').read_text());name=cfg['id']
    e=os.environ.copy();e.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONUNBUFFERED='1',XDG_CACHE_HOME=str(w/'cache'),CPG_WORK_ROOT=str(w),POCL_CACHE_DIR=str(w/'pocl-cache'),POCL_MAX_PTHREAD_COUNT='2')
    e.pop('PYTHONPATH',None);e.pop('LD_LIBRARY_PATH',None);e.pop('OCL_ICD_VENDORS',None)
    calls=[]
    def run(argv,label,cwd=w,timeout=300):
        argv=list(map(str,argv))
        try:
            q=subprocess.run(argv,cwd=cwd,env=e,capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            for stream,value in [('stdout',error.stdout),('stderr',error.stderr)]:
                if isinstance(value,bytes):value=value.decode(errors='replace')
                (w/(label+'.'+stream)).write_text(value or '')
            calls.append({'label':label,'argv':argv,'cwd':str(cwd),'returncode':None,'timed_out':True,'timeout_seconds':timeout})
            (w/'commands.json').write_text(json.dumps(calls,indent=2))
            raise
        (w/(label+'.stdout')).write_text(q.stdout);(w/(label+'.stderr')).write_text(q.stderr)
        calls.append({'label':label,'argv':argv,'cwd':str(cwd),'returncode':q.returncode});(w/'commands.json').write_text(json.dumps(calls,indent=2))
        require(q.returncode==0,label+' returned '+str(q.returncode)+'; evidence '+str(w))
        return q
    def python(script):
        if cfg.get('wheels'):
            return [p/'venv/bin/python','-S',p/'samples/venv_bootstrap.py',p/'venv/lib/python3.12/site-packages',script]
        return [sys.executable,'-S',script]
    if name in ('cltune','ktt'):
        libs=p/'native-opencl/pyopencl/.libs';e.update(OCL_ICD_VENDORS=str(libs),LD_LIBRARY_PATH=str(libs)+':'+str(p/'build'))
    elif name=='kernel-tuner':
        libs=p/'venv/lib/python3.12/site-packages/pyopencl/.libs';e.update(OCL_ICD_VENDORS=str(libs),LD_LIBRARY_PATH=str(libs))
    if name=='cppatf':
        run([p/'build/cppatf-check'],'search')
        report=json.loads((w/'cppatf-result.json').read_text())
        require(report['evaluated']==16 and report['invalid_executed']==0 and report['correctness'],'cppATF constraints/correctness failed')
        rows=[json.loads(x) for x in (w/'cppatf-trials.jsonl').read_text().splitlines()]
        require(report['best_seconds']==min(x['seconds'] for x in rows),'cppATF selected minimum differs from actual trials')
    elif name in ('pyatf','gptune','kernel-tuner','orio'):
        if name=='gptune':e['PYTHONPATH']=':'.join(str(p/'source'/x) for x in ('gptune','gptune-autotune','gptune-skopt'))
        elif name=='orio':e['PYTHONPATH']=str(p/'source/orio')
        run(python(p/'samples'/(name.replace('-','_')+'_check.py')),'functional',timeout=600)
        report=json.loads((w/(name+'-result.json')).read_text())
        require(report['status']=='pass','upstream functional report did not pass')
    elif name=='cltune':
        q=run([p/'build/cltune-check'],'search')
        upstream=json.loads((w/'cltune-upstream.json').read_text())
        results=upstream['results']
        require(len(results)==4,'CLTune did not retain exactly four correct configurations')
        text=q.stdout+q.stderr
        require(text.count('Results differ')==4,'CLTune did not reject all four incorrect configurations')
        require(all(x['parameters']['BAD']==0 for x in results),'CLTune retained an incorrect configuration')
        report={'status':'pass','backend':'PoCL CPU OpenCL','valid_configurations':4,'incorrect_configurations_rejected':4,'gpu_executed':False,'profiler':None,'upstream':upstream}
    elif name=='ktt':
        all_results=[]
        for negative in (False,True):
            d=w/('negative' if negative else 'positive');d.mkdir()
            kernel=p/'source/ktt/Tutorials/03KernelTuning/OpenClKernel.cl'
            if negative:
                bad=d/'wrong.cl';bad.write_text(kernel.read_text().replace('+ scalar;','+ scalar + 1.0f;'));kernel=bad
            run([p/'build/ktt-check','0','0',kernel],d.name,cwd=d)
            up=json.loads((d/'TuningOutput.json').read_text());rows=up['Results']
            require(len(rows)==4 and all(x['Status']==('ValidationFailed' if negative else 'Ok') for x in rows),'KTT native validation status mismatch')
            require(all(x['ProfilingOverhead']==0 for x in rows),'Unexpected profiler use')
            all_results.append(up)
        report={'status':'pass','backend':'PoCL CPU OpenCL','valid_configurations':4,'incorrect_configurations_rejected':4,'gpu_executed':False,'profiler':None,'positive':all_results[0],'negative':all_results[1]}
    elif name=='magpie':
        e['PYTHONPATH']=str(p/'source/magpie')
        scenario=(p/'samples/magpie-scenario.txt').read_text().replace('log_dir = evidence/magpie','log_dir = '+str(w/'logs')).replace('work_dir = build/magpie_work','work_dir = '+str(w/'variants')).replace('path = samples/magpie_case','path = '+str(p/'samples/magpie_case'))
        s=w/'scenario.txt';s.write_text(scenario)
        q=run([sys.executable,'-S','-m','magpie.bin.local_search','--scenario',s],'search',timeout=180)
        logs=list((w/'logs').glob('*.log'));patches=list((w/'logs').glob('*.patch'));diffs=list((w/'logs').glob('*.diff'))
        require(logs and patches and diffs,'Magpie did not persist patch/diff/log')
        text='\n'.join(x.read_text() for x in logs)
        require('TEST_CODE_ERROR' in text,'Magpie negative test candidate was not rejected')
        require('SUCCESS' in text,'Magpie did not measure valid variants')
        run([sys.executable,'-S','-m','magpie.bin.revalidate_patch','--scenario',s,'--patch',patches[0]],'best-replay',timeout=90)
        report={'status':'pass','backend':'native_cpu','search_budget_steps':40,'failing_tests_rejected':True,'patch':patches[0].name,'diff':diffs[0].read_text(),'fitness':'measured process execution time','best_replayed':True,'scope':'conditional research integration; small C example only'}
    else:raise RuntimeError('Unknown resource')
    require(report['status']=='pass','functional status failed')
    (w/(name+'-result.json')).write_text(json.dumps(report,indent=2,default=str)+'\n')
    result={'status':'passed','id':name,'work':str(w),'result':str(w/(name+'-result.json'))}
    print(json.dumps(result))

if __name__=='__main__':main()
