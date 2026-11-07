#!/usr/bin/env python3
from pathlib import Path
import argparse,subprocess,tempfile,os,json,time,sys

def runtime_env(pocl,loader,work):
 env={k:v for k,v in os.environ.items() if not k.startswith(('POCL_','OCL_ICD_','ZE_','ZEL_')) and k not in ('OPENCL_LAYERS','LD_PRELOAD')}
 empty=work/'empty-vendors';empty.mkdir(exist_ok=True)
 env.update(LD_LIBRARY_PATH=str(loader/'lib')+':'+str(pocl/'usr/lib/x86_64-linux-gnu')+':'+str(pocl/'usr/lib/llvm-16/lib')+':'+str(pocl/'usr/lib/x86_64-linux-gnu/pocl'),OCL_ICD_VENDORS=str(empty),OCL_ICD_FILENAMES=str(pocl/'usr/lib/x86_64-linux-gnu/libpocl.so.2'),POCL_DEVICES='basic',POCL_MAX_PTHREAD_COUNT='2',POCL_CACHE_DIR=str(work/'pocl-cache'))
 return env

def run(argv,env,cwd,out,name,timeout=600):
 start=time.monotonic();p=subprocess.run([str(a) for a in argv],cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
 row={'case':name,'argv':[str(a) for a in argv],'returncode':p.returncode,'elapsed_seconds':time.monotonic()-start,'stdout':p.stdout,'stderr':p.stderr};(out/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n');return row

def probe(pocl,loader,out):
 with tempfile.TemporaryDirectory(prefix='cpg-opencl-',dir=out) as temp:
  work=Path(temp);env=runtime_env(pocl,loader,work);env['POCL_CACHE_DIR']=str(out/'pocl-cache')
  row=run([pocl/'bin/cpg-opencl-probe'],env,work,out,'cpu-kernels')
  if row['returncode']!=0:raise RuntimeError(row['stderr'][-4000:])
  result=json.loads(row['stdout'])
  if result['status']!='passed' or result['platforms']!=1 or result['cpu_devices']!=1:raise RuntimeError('unexpected device scope')
  if Path(result['loader_path']).resolve()!=(loader/'lib/libOpenCL.so.1').resolve():raise RuntimeError('unexpected OpenCL loader')
  if 'PoCL 5.0' not in result['platform_version'] or 'LLVM 16.0.6' not in result['platform_version']:raise RuntimeError('unexpected PoCL/LLVM runtime version')
  env['OCL_ICD_FILENAMES']=''
  negative=run([pocl/'bin/cpg-opencl-probe','--expect-empty'],env,work,out,'empty-icd')
  if negative['returncode'] or json.loads(negative['stdout']).get('platforms')!=0:raise RuntimeError('unisolated ICD discovery')
  result.update(scope='CPU basic backend only; OpenCL C 1.2 kernels on PoCL 5.0+LLVM 16.0.6. No GPU or certification claim.',negative_empty_vendor_directory='passed')
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':'passed','kernels':4,'negative_cases':3,'device':result['device_name'],'loader_verified':True}))
  return result

def cts(prefix,pocl,loader,out):
 cases=json.loads((prefix/'share/opencl-cts/representative-cases.json').read_text())
 with tempfile.TemporaryDirectory(prefix='cpg-cts-',dir=out) as temp:
  import shutil
  work=Path(temp);env=runtime_env(pocl,loader,work);env['POCL_CACHE_DIR']=str(out/'pocl-cache')
  for directory in ('includeTestDirectory','secondIncludeTestDirectory'):
   shutil.copytree(prefix/'share/opencl-cts'/directory,work/directory)
  native_file=out/'upstream-results.json';env['CL_CONFORMANCE_RESULTS_FILENAME']=str(native_file)
  if native_file.exists():native_file.unlink()
  names=[c['name'] for c in cases]
  row=run([prefix/'bin/test_compiler',*names,'cpu','128'],env,work,out,'compiler-representatives',timeout=1700)
  if row['returncode']!=0 or not native_file.exists():raise RuntimeError('CTS execution failed: '+row['stdout'][-4000:]+row['stderr'][-2000:])
  native=json.loads(native_file.read_text());results=native.get('results',{})
  if set(results)!=set(names) or any(results.get(n)!='pass' for n in names):raise RuntimeError('CTS has failing, missing, skipped or unexpected cases: '+repr(results))
  result={'status':'passed','suite':'OpenCL-CTS v2025-01-22-00','device_profile':'PoCL 5.0 basic CPU / LLVM16.0.6 / device OpenCL 3.0 / OpenCL C 1.2','scope':'Exactly the declared compiler sub-suite representatives, seed 0 and num_elements 128. Full CTS and GPU not executed; no Khronos certification claim.','case_count':len(names),'cases':[{'name':n,'upstream_result':results[n],'status':'passed'} for n in names],'upstream_json':'upstream-results.json','command_log':'compiler-representatives.json'}
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='cases'}));return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['probe','cts']);p.add_argument('--prefix',type=Path,required=True);p.add_argument('--pocl',type=Path);p.add_argument('--loader',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.prefix=a.prefix.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
 if a.mode=='probe':probe(a.prefix,(a.loader or a.prefix/'support').resolve(),a.output)
 else:
  if not a.pocl or not a.loader:p.error('CTS requires --pocl and --loader prefixes')
  cts(a.prefix,a.pocl.resolve(),a.loader.resolve(),a.output)
