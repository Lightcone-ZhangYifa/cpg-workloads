#!/usr/bin/env python3
"""Offline bytecode profile; the installation prefix is read only."""
import argparse,json,os,shutil,subprocess,tempfile
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    p=Path(a.prefix).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').unlink(missing_ok=True)
    cfg=json.loads((p/'profile.json').read_text());rid=cfg['id']
    java=shutil.which('java')
    if not java:raise RuntimeError('Java 17 or newer runtime is required; no network installation is attempted')
    env=os.environ.copy()
    for k in ['JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH']:env.pop(k,None)
    work=Path(tempfile.mkdtemp(prefix='java-profile-',dir=out));classes=work/'classes';classes.mkdir()
    lib=os.pathsep.join(str(x) for x in sorted((p/'lib').glob('*.jar')))
    commands=[]
    def run(argv,name):
        r=subprocess.run(argv,cwd=work,env=env,text=True,capture_output=True,timeout=180)
        (out/(name+'.stdout.txt')).write_text(r.stdout);(out/(name+'.stderr.txt')).write_text(r.stderr)
        commands.append({'argv':argv,'returncode':r.returncode,'stdout':name+'.stdout.txt','stderr':name+'.stderr.txt'})
        if r.returncode:raise RuntimeError(name+' failed: '+r.stderr[-3000:])
        return r.stdout+r.stderr
    run([java,'-version'],'runtime')
    run([java,'-Xmx128m','-jar',str(p/'tools/ecj-3.37.0.jar'),'-1.8','-g','-proc:none','-classpath',lib,'-d',str(classes)]+[str(x) for x in sorted((p/'src').glob('*.java'))],'compile')
    args=[java,'-Xmx128m','-Xverify:all','-cp',os.pathsep.join([str(classes),lib]),'Probe']
    if rid=='research.bcel':args.append(str(classes/'Fixture.class'))
    probe_dir=out/'probe-output';probe_dir.mkdir(exist_ok=True);args.append(str(probe_dir))
    result=run(args,'probe');line=next(x[7:] for x in result.splitlines() if x.startswith('RESULT '));metrics=json.loads(line)
    if rid=='research.bcel':
        checks=[{'name':'single_instruction_mutation','passed':metrics['before']==1 and metrics['after']==2 and metrics['changed_instructions']==1},{'name':'class_attributes_preserved','passed':metrics['major_version']==52 and metrics['source_file']=='Fixture.java'},{'name':'malformed_class_rejected','passed':metrics['truncated_rejected']},{'name':'jvm_verifier_negative','passed':metrics['jvm_verifier_rejected_bad_stack']}]
    elif rid=='research.jvm-asm':
        checks=[{'name':'bytecode_rewrite_executes','passed':metrics['before']==1 and metrics['after']==5},{'name':'check_class_adapter_positive','passed':metrics['check_class_adapter_valid']},{'name':'check_class_adapter_negative','passed':metrics['check_class_adapter_rejected_bad_stack']},{'name':'jvm_verifier_negative','passed':metrics['jvm_verifier_rejected_bad_stack']}]
    else:
        checks=[{'name':'local_interception','passed':metrics['before']=='before' and metrics['after']=='after'},{'name':'typed_signature','passed':metrics['signature']=='()Ljava/lang/String;'},{'name':'other_method_unchanged','passed':metrics['untouched_result']==8},{'name':'type_mismatch_rejected','passed':metrics['incompatible_return_rejected']},{'name':'no_external_attach','passed':metrics['external_attach'] is False}]
    if not all(x['passed'] for x in checks):raise RuntimeError('semantic check failed')
    (out/'commands.json').write_text(json.dumps(commands,indent=2));(out/'metrics.json').write_text(json.dumps(metrics,indent=2))
    shutil.rmtree(work)
    ev=[str(x.relative_to(out)) for x in sorted(out.rglob('*')) if x.is_file() and x.name!='result.json']
    (out/'result.json').write_text(json.dumps({'schema_version':1,'resource_id':rid,'status':'passed','checks':checks,'metrics':metrics,'evidence_files':ev,'scope':cfg['scope'],'runtime':'host Java >=17; bytecode target Java 8; compilation uses bundled ECJ 3.37.0'},indent=2))
    print('CPG_CHECK_PASS '+rid)

if __name__=='__main__':main()
