#!/usr/bin/env python3
"""Bounded OpenCL C header consumption; no OpenCL driver is required."""
from pathlib import Path
import argparse,subprocess,tempfile,json,hashlib,re,sys,os
VERSIONS=(100,110,120,200,210,220,300,310)

def extension_index(root):
 rows=[]
 for h in sorted((root/'CL').glob('*.h')):
  guards=[]; lines=h.read_text().splitlines();i=0
  while i<len(lines):
   start=i+1;line=lines[i];i+=1
   while line.endswith('\\') and i<len(lines):line=line[:-1]+' '+lines[i];i+=1
   m=re.match(r'\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)',line)
   if m:
    op,arg=m.groups()
    if op in ('if','ifdef','ifndef'):guards.append(op+' '+arg.strip())
    elif op in ('elif','else') and guards: guards[-1]=op+' '+arg.strip()
    elif op=='endif' and guards:guards.pop()
   m=re.match(r'\s*#\s*define\s+(cl_[a-z][a-zA-Z0-9_]+)\s+1\s*(?:/\*.*)?$',line)
   if m:rows.append({'extension':m.group(1),'header':'CL/'+h.name,'line':start,'preprocessor_context':list(guards),'header_sha256':hashlib.sha256(h.read_bytes()).hexdigest()})
 return {'schema_version':1,'semantics':'Header declaration presence only; it does not establish device support. Windows interoperability declarations are indexed but not executed on Linux.','records':rows,'unique_extensions':len(set(r['extension'] for r in rows))}

def check(prefix,output):
 inc=prefix/'include'; results=[]
 def execute(cmd,expected,case,needle=None):
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
  ok=(p.returncode==0) if expected else p.returncode!=0 and (needle is None or needle in p.stderr)
  results.append({'case':case,'argv':cmd,'expected_success':expected,'returncode':p.returncode,'status':'passed' if ok else 'failed','stdout':p.stdout,'stderr':p.stderr})
  if not ok:raise RuntimeError(case+': '+p.stderr[-2000:])
 with tempfile.TemporaryDirectory(prefix='cpg-opencl-headers-',dir=output.parent) as tmp:
  d=Path(tmp)
  def compile_case(language,target,name,text,defs=(),expected=True,needle=None):
   ext='c' if language=='c' else 'cpp';src=d/(name+'.'+ext);src.write_text(text)
   compiler=os.environ.get('CC','gcc') if language=='c' else os.environ.get('CXX','g++')
   cmd=[compiler,'-std=c11' if language=='c' else '-std=c++17','-Werror','-fsyntax-only','-DCL_TARGET_OPENCL_VERSION='+str(target),*['-D'+x for x in defs],'-I'+str(inc),str(src)]
   execute(cmd,expected,language+':'+name,needle)
  for lang in ('c','cpp'):
   for v in VERSIONS:
    text='#include <CL/opencl.h>\n'
    for w in VERSIONS:
     macro='CL_VERSION_'+str(w//100)+'_'+str((w%100)//10)
     text+=('#ifndef ' if w<=v else '#ifdef ')+macro+'\n#error wrong_version_visibility\n#endif\n'
    text+='typedef char width_check[(sizeof(cl_uint)==4 && sizeof(cl_ulong)==8 && sizeof(cl_float4)==16)?1:-1];\nint main(void){return sizeof(&clGetPlatformIDs)==0;}\n'
    compile_case(lang,v,'target_'+str(v),text)
   for lo,hi,fn in [(100,110,'clCreateSubBuffer'),(110,120,'clCreateImage'),(120,200,'clCreateCommandQueueWithProperties'),(200,210,'clCreateProgramWithIL'),(210,220,'clSetProgramSpecializationConstant'),(220,300,'clSetContextDestructorCallback'),(300,310,'clGetKernelSuggestedLocalWorkSize')]:
    text='#include <CL/opencl.h>\nint main(void){return sizeof(&'+fn+')==0;}\n'
    compile_case(lang,hi,'api_'+fn+'_present',text)
    compile_case(lang,lo,'api_'+fn+'_hidden',text,expected=False,needle=fn)
   controls={'CL_NO_PROTOTYPES':(False,False,False),'CL_NO_CORE_PROTOTYPES':(False,True,True),'CL_NO_EXTENSION_PROTOTYPES':(True,False,False),'CL_NO_ICD_DISPATCH_EXTENSION_PROTOTYPES':(True,False,True),'CL_NO_NON_ICD_DISPATCH_EXTENSION_PROTOTYPES':(True,True,False)}
   for control,vis in controls.items():
    for fn,visible in zip(('clGetPlatformIDs','clGetGLContextInfoKHR','clCreateProgramWithILKHR'),vis):
     compile_case(lang,310,control+'_'+fn,'#include <CL/opencl.h>\nint main(void){return sizeof(&'+fn+')==0;}\n',(control,),visible,fn)
   compile_case(lang,310,'no_prototypes_typedefs','#include <CL/opencl.h>\n#include <CL/cl_function_types.h>\nint main(void){return sizeof(clGetPlatformIDs_fn)+sizeof(clCreateProgramWithILKHR_fn)==0;}\n',('CL_NO_PROTOTYPES',))
   for beta in (False,True):
    text='#include <CL/opencl.h>\n'+('#ifndef' if beta else '#ifdef')+' cl_khr_command_buffer\n#error beta_visibility\n#endif\nint main(void){return 0;}\n'
    compile_case(lang,310,'beta_'+str(beta),text,('CL_ENABLE_BETA_EXTENSIONS',) if beta else ())
  index=extension_index(inc)
  if index['unique_extensions']<100:raise RuntimeError('extension index unexpectedly incomplete')
  expected=prefix/'share/opencl-headers/extension-index.json'
  if expected.exists() and index!=json.loads(expected.read_text()):raise RuntimeError('extension index differs from installed headers')
  (output.parent/'extension-index.json').write_text(json.dumps(index,indent=2)+'\n')
  result={'status':'passed','scope':'C11/C++17 compile-only consumer, version/prototype/beta gates and source-location extension index; no device execution or conformance claim.','cases':results,'case_count':len(results),'extension_records':len(index['records']),'unique_extensions':index['unique_extensions']}
  output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='cases'}))

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--prefix',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--index-only',action='store_true');o=a.parse_args();o.output.parent.mkdir(parents=True,exist_ok=True)
 if o.index_only:o.output.write_text(json.dumps(extension_index(o.prefix/'include'),indent=2)+'\n')
 else:check(o.prefix.resolve(),o.output.resolve())
