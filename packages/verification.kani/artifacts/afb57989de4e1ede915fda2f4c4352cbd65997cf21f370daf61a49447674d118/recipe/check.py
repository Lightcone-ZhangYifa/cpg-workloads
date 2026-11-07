"""Run original CPG member and ELF gates, then the real bounded profile."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,uuid
from compiler_playground.packages.archive import verify_package
from compiler_playground.packages.compatibility import check_binary_runtime
from compiler_playground.packages.manager import current_target
prefix=Path(sys.argv[1]).resolve();build=Path.cwd();evidence=build/'functional-evidence';evidence.mkdir(parents=True,exist_ok=True)
lock=json.loads((prefix/'capsule-lock.json').read_text());runtime_root=build/'runtime-build';runtime_root.mkdir(exist_ok=True)
record={'capsule_sha256':lock['sha256'],'capsule_bytes':lock['bytes'],'resource_id':lock['id'],'verification':'original CPG verify_package and check_binary_runtime; no fabricated target'}
record_path=evidence/('capsule-'+uuid.uuid4().hex+'.json')
with tempfile.TemporaryDirectory(prefix=lock['id']+'-',dir=runtime_root) as temp:
    verified=verify_package(prefix/'runtime.cpgpkg.tar.gz',extract=Path(temp)/'tree',expected_sha256=lock['sha256'],expected_bytes=lock['bytes'])
    if verified['manifest']['package']['id']!=lock['id']:raise RuntimeError('Wrong runtime capsule identity')
    manifest=(prefix/'runtime-manifest.json').read_bytes()
    if hashlib.sha256(manifest).hexdigest()!=lock['manifest_file_sha256']:raise RuntimeError('Runtime manifest copy differs')
    if json.loads(manifest)!=verified['manifest']:raise RuntimeError('Runtime capsule manifest differs')
    record['verified']=True;record['manifest_sha256']=lock['manifest_file_sha256']
    payload=Path(temp)/'tree/payload';private=payload/lock['private_library_dir']
    if not private.is_dir():raise RuntimeError('Declared private library directory is absent')
    declared={'LD_LIBRARY_PATH':str(private)}
    target=current_target();rows=[]
    record['compatibility']={'actual_target':target,'declared_environment':declared,'evidence':rows,'status':'checking'}
    record_path.write_text(json.dumps(record,indent=2)+'\n')
    try:
        check_binary_runtime(payload,actual_target=target,environment=declared,evidence=rows)
        if not any(row.get('kind')=='elf_runtime' for row in rows):raise RuntimeError('No real ELF runtime was checked')
        record['compatibility']['status']='passed'
    except Exception as error:
        record['compatibility'].update(status='failed',error=repr(error))
        raise
    finally:
        record_path.write_text(json.dumps(record,indent=2)+'\n')
    runtime_env={key:value for key,value in os.environ.items() if not key.startswith('LD_')}
    runtime_env.update(declared)
    argv=[sys.executable,str(Path(__file__).with_name('functional.py')),str(payload)]
    record['functional_argv']=argv;record_path.write_text(json.dumps(record,indent=2)+'\n')
    run=subprocess.run(argv,cwd=build,env=runtime_env,text=True,capture_output=True,timeout=800)
    record.update({'functional_returncode':run.returncode,'stdout_sha256':hashlib.sha256(run.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(run.stderr.encode()).hexdigest()})
    record_path.write_text(json.dumps(record,indent=2)+'\n')
    print(run.stdout,end='');print(run.stderr,end='',file=sys.stderr)
    if run.returncode!=0:raise RuntimeError('Runtime functional profile failed')
record['expanded_runtime_removed']=True;record_path.write_text(json.dumps(record,indent=2)+'\n')
