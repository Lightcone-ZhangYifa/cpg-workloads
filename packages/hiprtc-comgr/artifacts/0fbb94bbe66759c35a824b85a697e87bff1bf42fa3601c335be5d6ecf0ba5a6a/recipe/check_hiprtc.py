#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import importlib.util

p=argparse.ArgumentParser()
p.add_argument('--prefix',type=Path,required=True)
p.add_argument('--work',type=Path,required=True)
a=p.parse_args()
prefix=a.prefix.resolve();a.work.mkdir(parents=True,exist_ok=True)
module_path=Path(__file__).with_name('hiprtc_adapter.py')
if not module_path.exists():
    module_path=Path(__file__).resolve().parents[1]/'scripts/hiprtc_adapter.py'
spec=importlib.util.spec_from_file_location('cpg_hiprtc',module_path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
compiler=module.OfflineCompiler(prefix)
try:
    compiler.validate_target('gfx999999')
except ValueError:
    print('UNSUPPORTED_TARGET_REJECTED_BEFORE_COMPILER',flush=True)
else:
    raise RuntimeError('Invalid architecture reached vendor compiler')
client_result=compiler.compile_cpp('extern "C" __global__ void fill(int*x){x[0]=7;}',target='gfx1100')
if client_result['bytes'][:4]!=b'\x7fELF':raise RuntimeError('Python client did not compile ELF')
with tempfile.TemporaryDirectory(prefix='hiprtc-',dir=a.work) as tmp:
    tmp=Path(tmp).resolve();exe=tmp/'consumer';out=tmp/'outputs';out.mkdir()
    source=Path(__file__).with_name('hiprtc_comgr.cpp')
    argv=['c++','-std=c++17','-O2','-pipe','-Wall','-Wextra','-Werror','-I'+str(prefix/'include'),str(source),
          '-L'+str(prefix/'lib'),'-lhiprtc','-lamd_comgr','-Wl,-rpath,'+str(prefix/'lib'),'-o',str(exe)]
    env={**os.environ,'LD_LIBRARY_PATH':str(prefix/'lib'),'AMD_COMGR_CACHE':'0','TMPDIR':str(tmp)}
    for command in [argv,[str(exe),str(out)]]:
        run=subprocess.run(command,env=env,cwd=tmp,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
        print(json.dumps({'argv':command,'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr}),flush=True)
        if run.returncode:raise RuntimeError('HIPRTC/Comgr consumer command failed')
    if 'HIPRTC_COMGR_OFFLINE_OK' not in run.stdout:raise RuntimeError('Missing completion marker')
    outputs=[]
    for f in sorted(out.iterdir()):
        data=f.read_bytes()
        if f.suffix=='.hsaco' and (data[:4]!=b'\x7fELF' or int.from_bytes(data[18:20],'little')!=224):
            raise RuntimeError('Invalid AMDGPU code object')
        outputs.append({'file':f.name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        (a.work/f.name).write_bytes(data)
    summary={'status':'passed','rocm_release':'7.0.2','architectures':['gfx90a','gfx1100'],
             'negative_cases':['invalid source rejected by HIPRTC','unsupported explicit architecture rejected by Comgr-backed adapter before HIPRTC'],
             'linkage':'HIPRTC generated matching LLVM bitcode; Comgr linked two modules, generated and linked an AMDGPU executable',
             'outputs':outputs,'gpu_execution':'not_run; no device or driver is deployed'}
    (a.work/'hiprtc-comgr-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))
