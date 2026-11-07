#!/usr/bin/env python3
"""Run unchanged OpenMP V&V sources and classify compiler, run and device outcomes."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SMOKE=[
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for.c',
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for_reduction.c',
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for_firstprivate.c',
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for_map_tofrom.c',
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for_map_from.c',
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for_map_to.c',
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for_private.c',
 'tests/4.5/target_teams_distribute_parallel_for/test_target_teams_distribute_parallel_for_schedule_private.c',
]


def capture(argv,env,timeout=45):
    try:
        r=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=timeout)
        return dict(argv=argv,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr,timed_out=False)
    except subprocess.TimeoutExpired as e:
        return dict(argv=argv,returncode=None,stdout=str(e.stdout or ''),stderr=str(e.stderr or ''),timed_out=True)


def classify(compilation,run,device,uses_target=True):
    if compilation['timed_out']:return 'compile_timeout'
    if compilation['returncode']!=0:return 'compile_failure'
    if run is None:return 'not_run'
    if run['timed_out']:return 'run_timeout'
    if run['returncode']==(-667)%256:return 'skipped'
    if run['returncode']!=0:return 'run_failure'
    if 'Test failed' in run['stdout']:return 'run_failure'
    if not uses_target:return 'host_execution'
    return 'device_offload' if device['target_initial_device']==0 else 'host_fallback'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True,type=Path);ap.add_argument('--work',required=True,type=Path)
    ap.add_argument('--cc',default=os.environ.get('CC','gcc'));ap.add_argument('--test',action='append',default=[])
    ap.add_argument('--offload',choices=['disabled','mandatory'],default='disabled');a=ap.parse_args()
    a.work.mkdir(parents=True,exist_ok=True);recipe=Path(__file__).resolve().parent
    root=a.prefix/'share/openmp-vv';index=json.loads((a.prefix/'share/openmp-vv-index.json').read_text())
    requested=a.test or SMOKE
    if a.offload=='mandatory' and any(rel not in SMOKE for rel in requested):
        (a.work/'result.json').write_text(json.dumps({'status':'blocked','classification':'unreviewed_device_profile','scope':'Mandatory device qualification is limited to the eight reviewed unconditional-target smoke tests.','upstream_tests_run':0},indent=2)+'\n')
        raise SystemExit(77)
    env=dict(os.environ,OMP_NUM_THREADS='2',OMP_THREAD_LIMIT='4',OMP_TARGET_OFFLOAD=a.offload.upper())
    compiler=capture([a.cc,'--version'],env)
    flags=['-std=c11','-O1','-fopenmp','-DVERBOSE_MODE','-DOMPVV_NUM_THREADS_HOST=2','-DOMPVV_NUM_THREADS_DEVICE=2','-DOMPVV_NUM_TEAMS_HOST=2','-DOMPVV_NUM_TEAMS_DEVICE=2']
    probe=a.work/'device-probe'
    pc=capture([a.cc,'-O1','-fopenmp',str(recipe/'probe.c'),'-o',str(probe)],env)
    if pc['returncode']!=0:
        (a.work/'result.json').write_text(json.dumps({'status':'failed','classification':'probe_compile_failure','compiler':compiler,'probe_compile':pc,'upstream_tests_run':0},indent=2)+'\n')
        raise SystemExit(1)
    availability_run=capture([str(probe),'--devices'],env)
    if availability_run['returncode']!=0:
        (a.work/'result.json').write_text(json.dumps({'status':'failed','classification':'device_query_run_failure','compiler':compiler,'probe_compile':pc,'device_query':availability_run,'upstream_tests_run':0},indent=2)+'\n')
        raise SystemExit(1)
    availability=json.loads(availability_run['stdout'])
    if a.offload=='mandatory' and availability['num_devices']==0:
        (a.work/'result.json').write_text(json.dumps({'status':'blocked','classification':'no_offload_device','compiler':compiler,'probe_compile':pc,'device_query':availability_run,'availability':availability,'device_qualified':False,'upstream_tests_run':0},indent=2)+'\n')
        raise SystemExit(77)
    pr=capture([str(probe)],env)
    if pr['returncode']!=0:
        out={'status':'failed','classification':'probe_run_failure','offload_policy':a.offload,'compiler':compiler,'probe_compile':pc,'probe_run':pr,'device_query':availability_run,'upstream_tests_run':0}
        (a.work/'result.json').write_text(json.dumps(out,indent=2)+'\n')
        raise SystemExit(1)
    device=json.loads(pr['stdout'])
    if a.offload=='mandatory' and device['target_initial_device']!=0:
        raise SystemExit('mandatory offload unexpectedly ran on host')
    by_path={r['path']:r for r in index};records=[]
    for number,rel in enumerate(requested):
        if rel not in by_path:raise SystemExit('test is not in frozen upstream index: '+rel)
        row=by_path[rel];source=root/rel
        if hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('source changed: '+rel)
        if row['language']!='C':raise SystemExit('this bounded compiler profile accepts C tests; use an explicitly qualified C++/Fortran profile')
        exe=a.work/('test-'+str(number))
        comp=capture([a.cc,*flags,'-I'+str(root/'ompvv'),str(source),'-lm','-o',str(exe)],env)
        run=capture([str(exe)],env) if comp['returncode']==0 else None
        status=classify(comp,run,device,row['has_target_directive'])
        records.append(dict(path=rel,specification_version=row['specification_version'],source_sha256=row['sha256'],expected=row['expected'],compile=comp,run=run,classification=status,classification_basis='mandatory offload plus successful device probe and reviewed unconditional target regions' if status=='device_offload' else 'frozen source target flag, selected offload policy and actual compiler/runtime results'))
    # These two fixtures test classification only and are not counted as upstream tests.
    invalid=a.work/'invalid.c';invalid.write_text('#error CPG_INTENTIONAL_COMPILE_NEGATIVE\n')
    bad_compile=capture([a.cc,'-c',str(invalid),'-o',str(a.work/'invalid.o')],env)
    runtime=a.work/'runtime-negative.c';runtime.write_text('int main(void){return 7;}\n')
    runtime_exe=a.work/'runtime-negative'
    good_compile=capture([a.cc,str(runtime),'-o',str(runtime_exe)],env);bad_run=capture([str(runtime_exe)],env)
    negatives=[dict(kind='synthetic_compile_failure',compile=bad_compile,classification=classify(bad_compile,None,device)),dict(kind='synthetic_run_failure',compile=good_compile,run=bad_run,classification=classify(good_compile,bad_run,device))]
    negatives_ok=negatives[0]['classification']=='compile_failure' and negatives[1]['classification']=='run_failure'
    if a.offload=='disabled' and availability['num_devices']==0:
        guard=capture([sys.executable,str(recipe/'check.py'),'--prefix',str(a.prefix),'--work',str(a.work/'mandatory-negative'),'--cc',a.cc,'--offload','mandatory'],env,timeout=90)
        guard_result_path=a.work/'mandatory-negative/result.json'
        guard_result=json.loads(guard_result_path.read_text()) if guard_result_path.exists() else {}
        guard_ok=guard['returncode']==77 and guard_result.get('classification')=='no_offload_device' and guard_result.get('upstream_tests_run')==0
        negatives.append(dict(kind='executed_mandatory_without_device',execution=guard,result=guard_result,passed=guard_ok))
        negatives_ok=negatives_ok and guard_ok
    functional_ok=all(r['classification'] in {'host_execution','host_fallback','device_offload'} and '[OMPVV_RESULT:' in r['run']['stdout'] for r in records)
    out=dict(status='passed' if functional_ok and negatives_ok else 'failed',compiler=compiler,compiler_flags=flags,environment={k:env[k] for k in ('OMP_NUM_THREADS','OMP_THREAD_LIMIT','OMP_TARGET_OFFLOAD')},device=device,
             device_availability=availability,device_query=availability_run,corpus_tests=len(index),corpus_by_spec=dict(Counter(r['specification_version'] for r in index)),
             upstream_tests_run=len(records),classifications=dict(Counter(r['classification'] for r in records)),
             unexecuted_tests=len(index)-len(records),device_qualified=bool(functional_ok and a.offload=='mandatory' and availability['num_devices']>0 and all(r['classification']=='device_offload' for r in records)),
             notes='Host fallback success is not device offload or whole-spec conformance. Index only is not execution.',records=records,negative_controls=negatives)
    (a.work/'result.json').write_text(json.dumps(out,indent=2)+'\n')
    if out['status']!='passed':raise SystemExit('OpenMP V&V bounded functional profile failed; see result.json')
    print(json.dumps({'status':'passed','tests':len(records),'device_qualified':out['device_qualified'],'marker':'OPENMP_VV_FUNCTIONAL_OK'}))


if __name__=='__main__':main()
