import json, pathlib
import numpy as np
import pyopencl as cl
from kernel_tuner import tune_kernel, run_kernel

def require(c,m):
    if not c:raise RuntimeError(m)

n=262144
rng=np.random.default_rng(84)
a=rng.integers(0,100,n).astype(np.float32)
b=rng.integers(0,100,n).astype(np.float32)
c=np.zeros_like(a)
source='''__kernel void vector_add(__global const float*a,__global const float*b,__global float*c,const int n) {
int i=get_global_id(0);if(i<n)c[i]=a[i]+b[i];}'''
args=[a,b,c,np.int32(n)]
results,env=tune_kernel('vector_add',source,n,args,{'block_size_x':[32,64,128,256]},
    lang='OpenCL',answer=[None,None,a+b,None],iterations=3,quiet=True)
require(len(results)==4,'configuration count mismatch')
require(all(np.isfinite(r['time']) and r['time']>0 for r in results),'invalid kernel timing')
best=min(results,key=lambda r:r['time'])
answer=run_kernel('vector_add',source,n,args,{'block_size_x':best['block_size_x']},lang='OpenCL')
require(np.array_equal(answer[2],a+b),'replay oracle mismatch')
negative=False
try:
    tune_kernel('vector_add',source.replace('a[i]+b[i]','a[i]+b[i]+1.0f'),n,args,
                {'block_size_x':[32]},lang='OpenCL',answer=[None,None,a+b,None],iterations=1,quiet=True)
except RuntimeError as error:
    require('Kernel result verification failed' in str(error),
            'incorrect-output test failed for an unrelated reason: '+str(error))
    negative=True
require(negative,'incorrect kernel was accepted')
platform=cl.get_platforms()[0]; device=platform.get_devices()[0]
report={'status':'pass','backend':'OpenCL CPU','device':device.name,'platform':platform.name,
        'evaluated':4,'results':results,'best_block_size_x':best['block_size_x'],
        'best_time_ms':best['time'],'replay_correct':True,'negative_bad_output_rejected':negative,
        'gpu_executed':False,'system_profiler':None}
pathlib.Path('kernel-tuner-result.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
print(json.dumps(report,default=str))
