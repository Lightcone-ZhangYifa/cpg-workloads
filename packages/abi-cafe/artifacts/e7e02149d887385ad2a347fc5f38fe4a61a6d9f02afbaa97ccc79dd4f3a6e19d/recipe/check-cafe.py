#!/usr/bin/env python3
"""Run bounded C/Rust compatibility tests sequentially and verify minimization."""
import argparse,hashlib,json,os,pathlib,shutil,subprocess,sys,signal
if sys.flags.optimize:raise SystemExit('Optimized Python disables required validation; use normal python3 without -O or PYTHONOPTIMIZE.')
p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[1]);p.add_argument('--out',type=pathlib.Path,required=True);p.add_argument('--rust-bin',type=pathlib.Path);p.add_argument('--smoke',action='store_true');a=p.parse_args()
a.root=a.root.resolve();a.out=a.out.resolve()
assert not a.out.is_relative_to(a.root), 'Outputs must be external to immutable package'
assert not a.out.exists() or not any(a.out.iterdir()), 'Output must be fresh or empty'
a.out.mkdir(parents=True,exist_ok=True)
rust_bin=a.rust_bin.resolve() if a.rust_bin else a.root/'toolchain/bin'
if not (rust_bin/'rustc').exists() and a.rust_bin is None:raise SystemExit('Set --rust-bin to the fixed Rust 1.88.0 bin directory, or install the bundled toolchain at toolchain/.')
env=os.environ.copy();env['PATH']=str(rust_bin)+os.pathsep+env.get('PATH','');env['CARGO_NET_OFFLINE']='true';env['TOKIO_WORKER_THREADS']='1';env['RAYON_NUM_THREADS']='1';env['CARGO_BUILD_JOBS']='1'
versions={}
for compiler,args in [('rustc',['rustc','-vV']),('gcc',['gcc','--version'])]:
    r=subprocess.run(args,env=env,capture_output=True,text=True,check=True);versions[compiler]=r.stdout
assert versions['rustc'].splitlines()[0].startswith('rustc 1.88.0 ')
gcc_version=subprocess.check_output(['gcc','-dumpfullversion'],env=env,text=True).strip()
gcc_target=subprocess.check_output(['gcc','-dumpmachine'],env=env,text=True).strip()
assert gcc_version=='13.3.0' and gcc_target=='x86_64-linux-gnu', 'This recorded pairing requires GCC 13.3.0 targeting x86_64-linux-gnu; other compilers require a new measured profile.'
versions['gcc_fullversion']=gcc_version;versions['gcc_target']=gcc_target
binary=a.root/'bin/abi-cafe';assert binary.is_file()
base=[str(binary),'--toolchains','gcc,rustc','--pairs','gcc_calls_rustc,rustc_calls_gcc','--conventions','c','--reprs','c','--output-format','json']
commands=[];positive=[];subtests=0
tests=['FixedAggregate'] if a.smoke else ['SimpleStruct','SimplePaddedStruct','U8Array','FixedAggregate']
seeds=['graffiti'] if a.smoke else ['graffiti','random17']
def execute(label,args,expect_success):
    out=a.out/label;out.mkdir()
    cmd=base+args
    with (out/'stdout.json').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
        proc=subprocess.Popen(cmd,cwd=out,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        try:code=proc.wait(timeout=600)
        except BaseException:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            raise
    commands.append({'argv':cmd,'returncode':code,'cwd':label,'stdout':label+'/stdout.json','stderr':label+'/stderr.log'})
    if expect_success:assert code==0,f'{label} failed: inspect stderr.log'
    else:assert code==1,f'{label} must report an ordinary test failure (exit 1), got {code}'
    report=json.loads((out/'stdout.json').read_text())
    assert report['summary']['num_tests']==2,report['summary']
    assert len(report['tests'])==2, 'Exactly two complete test records required'
    assert {(t['key']['caller'],t['key']['callee']) for t in report['tests']}=={('gcc','rustc'),('rustc','gcc')}, 'Both directions required'
    return out,report
for test in tests:
    for seed in seeds:
        if test=='SimplePaddedStruct' and seed=='random17':continue
        out,report=execute(test+'-'+seed,['--tests',test,'--add-tests',str(a.root/'fixtures/positive'),'--gen-vals',seed],True)
        assert report['summary']=={'num_tests':2,'num_passed':2,'num_busted':0,'num_failed':0,'num_skipped':0},report['summary']
        for t in report['tests']:
            assert t['conclusion']=='passed' and t['results']['ran_to']=='check' and t['results']['check']['all_passed']
            checks=t['results']['check']['subtest_checks'];assert checks and all('Ok' in x['result'] for x in checks);subtests+=len(checks)
        positive.append({'test':test,'values':seed,**report['summary']})
negative=[]
if not a.smoke:
    out,report=execute('negative-control',['--disable-builtin-tests','--disable-builtin-rules','--add-tests',str(a.root/'fixtures/negative'),'--gen-vals','graffiti'],False)
    assert report['summary']=={'num_tests':2,'num_passed':0,'num_busted':0,'num_failed':2,'num_skipped':0}
    for t in report['tests']:
        assert t['conclusion']=='failed' and t['results']['ran_to']=='check'
        checks=t['results']['check']['subtest_checks'];assert len(checks)==2 and 'Err' in checks[0]['result'] and 'Ok' in checks[1]['result']
        mini=checks[0]['minimized'];assert mini
        files=[]
        for field in ['caller_src','callee_src']:
            rel=pathlib.PurePosixPath(mini[field]);assert not rel.is_absolute() and '..' not in rel.parts
            path=(out/mini[field]).resolve();assert path.is_relative_to(out.resolve()) and path.is_file()
            code=path.read_text();assert 'mismatch' in code and 'void control(' not in code and 'fn control(' not in code
            files.append({'path':path.relative_to(a.out).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size})
        negative.append({'pair':t['key']['caller']+'_calls_'+t['key']['callee'],'failure_stage':'check','control_subtest':'passed','minimized':files})
    assert len(negative)==2 and sum(len(x['minimized']) for x in negative)==4
result={'schema_version':1,'entity_id':'abi-cafe','status':'passed','mode':'smoke' if a.smoke else 'full-bounded','toolchains':versions,'concurrency':{'TOKIO_WORKER_THREADS':1,'RAYON_NUM_THREADS':1,'CARGO_BUILD_JOBS':1},'positive_test_combinations':sum(x['num_tests'] for x in positive),'positive_subtests':subtests,'positive':positive,'negative_controls':negative,'generated_minimized_files':sum(len(x['minimized']) for x in negative),'commands':commands,'known_excluded_case':{'test':'SimplePaddedStruct','values':'random17','reason':'Pinned upstream C generator emits invalid NaNf for this random stream; actual compile/link failure preserved in known-limitations.json and evidence. Not an ABI failure and not counted as passed.'},'scope':'Finite descriptive compatibility tests. The negative input intentionally mismatches a float and integer ABI and is undefined at the FFI boundary; it proves reporting/minimization, not a compiler bug or standards correctness.'}
(a.out/'results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
