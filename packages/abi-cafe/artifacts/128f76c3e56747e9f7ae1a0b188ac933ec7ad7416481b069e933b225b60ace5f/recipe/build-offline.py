#!/usr/bin/env python3
"""Fresh source build from hashed source/vendor archives, no shared mutable cache."""
import argparse,hashlib,json,os,pathlib,shutil,subprocess,tarfile,sys
if sys.flags.optimize:raise SystemExit('Optimized Python disables required validation; use normal python3 without -O or PYTHONOPTIMIZE.')
p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[1]);p.add_argument('--sdk',type=pathlib.Path,required=True);p.add_argument('--work',type=pathlib.Path,required=True);p.add_argument('--prefix',type=pathlib.Path,required=True);p.add_argument('--jobs',type=int,default=1);a=p.parse_args()
a.root=a.root.resolve();a.sdk=a.sdk.resolve();a.work=a.work.resolve();a.prefix=a.prefix.resolve()
assert 1<=a.jobs<=4
assert not a.work.is_relative_to(a.root) and not a.prefix.is_relative_to(a.root)
assert not a.work.is_relative_to(a.prefix) and not a.prefix.is_relative_to(a.work)
for output in [a.work,a.prefix]:
    for immutable in [a.root,a.sdk]:
        assert not output.is_relative_to(immutable) and not immutable.is_relative_to(output), 'Input/SDK/output trees must be disjoint'
for d in [a.work,a.prefix]:
    assert not d.exists() or not any(d.iterdir()), f'Must be fresh or empty: {d}'
    d.mkdir(parents=True,exist_ok=True)
lock=json.loads((a.root/'source-inputs.json').read_text())
for rec in lock['inputs']:
    rel=pathlib.PurePosixPath(rec['path']);assert not rel.is_absolute() and '..' not in rel.parts
    src=(a.root/rec['path']).resolve();assert src.is_relative_to(a.root)
    assert hashlib.sha256(src.read_bytes()).hexdigest()==rec['sha256'],f'Input hash mismatch: {src}'
    with tarfile.open(src) as tf:tf.extractall(a.work,filter='data')
source=a.work/'source';(source/'.cargo').mkdir(exist_ok=True)
(source/'.cargo/config.toml').write_text('[source.crates-io]\nreplace-with = "vendored-sources"\n[source.vendored-sources]\ndirectory = "../vendor"\n[net]\noffline = true\n')
env=os.environ.copy();env['PATH']=str(a.sdk/'bin')+os.pathsep+env.get('PATH','');env['CARGO_HOME']=str(a.work/'cargo-home');env['CARGO_TARGET_DIR']=str(a.work/'target');env['CARGO_NET_OFFLINE']='true'
version=subprocess.check_output([str(a.sdk/'bin/rustc'),'-vV'],env=env,text=True)
assert version.splitlines()[0].startswith('rustc 1.88.0 '), version
cmd=[str(a.sdk/'bin/cargo'),'build','--offline','--locked','--release','-j',str(a.jobs)]
with (a.work/'build.log').open('w') as f:r=subprocess.run(cmd,cwd=source,env=env,stdout=f,stderr=subprocess.STDOUT)
if r.returncode:raise SystemExit(f'Offline build failed ({r.returncode}); inspect {a.work}/build.log')
for name in ['fixtures','scripts','docs']:
    if (a.root/name).exists():shutil.copytree(a.root/name,a.prefix/name)
for name in ['README.zh.txt','sources-lock.json','source-inputs.json','toolchain-lock.json','known-limitations.json','dependency-licenses.json']:
    if (a.root/name).exists():shutil.copyfile(a.root/name,a.prefix/name)
(a.prefix/'bin').mkdir(exist_ok=True);shutil.copy2(a.work/'target/release/abi-cafe',a.prefix/'bin/abi-cafe');(a.prefix/'bin/abi-cafe').chmod(0o755)
report={'schema_version':1,'status':'passed','source_commit':lock['commit'],'rustc':version,'command':cmd,'network_mode':'CARGO_NET_OFFLINE=true plus vendor source replacement; run under provided seccomp guard for network-denial evidence','binary_sha256':hashlib.sha256((a.prefix/'bin/abi-cafe').read_bytes()).hexdigest(),'prefix':str(a.prefix),'work':str(a.work)}
(a.work/'build-result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
