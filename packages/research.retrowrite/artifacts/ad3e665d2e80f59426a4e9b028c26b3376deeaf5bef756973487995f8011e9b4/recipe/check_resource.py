#!/usr/bin/env python3
"""Bounded executable checks for worker075 resources; no network acquisition."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid

FIXTURE = r'''#include <stdio.h>
#include <stdlib.h>
__attribute__((noinline)) long fold(long a,long b,long c,long d,long e,long f,long g,long h) {
  long x=a+3*b-5*c+7*d-11*e+13*f-17*g+19*h;
  for(int i=0;i<5;i++) x=(x%100000)*3+i;
  return x;
}
int main(int argc,char **argv) {
  long x=argc>1?strtol(argv[1],0,10):7;
  printf("%ld\n",fold(x,x+1,x-2,x+3,4,9,-3,21));return 0;
}
'''

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def reference(x):
    value=x+3*(x+1)-5*(x-2)+7*(x+3)-11*4+13*9-17*(-3)+19*21
    for i in range(5):
        rem=abs(value)%100000
        if value < 0:
            rem=-rem
        value=rem*3+i
    return f'{value}\n'

def verify_inventory(prefix):
    inventory=json.loads((prefix/'INVENTORY.json').read_text())
    require(isinstance(inventory,list) and bool(inventory),'Missing installed payload inventory')
    for row in inventory:
        path=prefix/row['path']
        require(path.is_file() and path.stat().st_size == row['bytes'] and sha(path)==row['sha256'],
                'Installed payload changed: '+row['path'])
    return len(inventory)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('resource',choices=['gtirb-rewriting','retrowrite','revng','llvm-mctoll'])
    parser.add_argument('prefix',type=Path)
    parser.add_argument('build',type=Path)
    args=parser.parse_args()
    prefix=args.prefix.resolve()
    args.build.mkdir(parents=True,exist_ok=True)
    nonce=uuid.uuid4().hex
    work=Path(tempfile.mkdtemp(prefix='semantic-'+nonce[:12]+'-',dir=args.build)).resolve()
    result={'schema_version':1,'resource':args.resource,'nonce':nonce,'status':'running',
            'work':str(work),'prefix':str(prefix),'commands':[],'files':{}}
    env={**os.environ,'PYTHONPATH':str(prefix/'lib/python'),'PYTHONDONTWRITEBYTECODE':'1',
         'PYTHONNOUSERSITE':'1','PIP_NO_INDEX':'1','LC_ALL':'C','OMP_NUM_THREADS':'1'}
    env.pop('PYTHONSTARTUP',None)
    def run(argv,name,timeout=600,expected=0,cwd=None):
        argv=[str(x) for x in argv]
        completed=subprocess.run(argv,cwd=cwd or work,env=env,capture_output=True,timeout=timeout)
        out,err=work/(name+'.stdout'),work/(name+'.stderr')
        out.write_bytes(completed.stdout);err.write_bytes(completed.stderr)
        result['commands'].append({'name':name,'argv':argv,'returncode':completed.returncode,
             'stdout':out.name,'stderr':err.name,'stdout_sha256':sha(out),'stderr_sha256':sha(err)})
        require(completed.returncode==expected,f'{name} returned {completed.returncode}: '+completed.stderr.decode(errors='replace')[-2000:])
        return completed
    try:
        result['installed_files_verified']=verify_inventory(prefix)
        (work/'abi.c').write_text(FIXTURE)
        run(['gcc','-O1','-fPIE','-pie','-fno-inline','-fcf-protection=none',work/'abi.c','-o',work/'original'],'compile')
        original=(work/'original').read_bytes()
        require(original[:4]==b'\x7fELF' and original[4:6]==b'\x02\x01','Expected ELF64 little endian')
        require(struct.unpack_from('<H',original,16)[0]==3 and struct.unpack_from('<H',original,18)[0]==62,'Expected x86-64 PIE input')
        symbol_text=run(['readelf','--syms','--wide',work/'original'],'symbols').stdout.decode()
        require(' fold' in symbol_text and ' main' in symbol_text,'Input is not the controlled symbolic fixture')
        result['input']={'format':'ELF64','architecture':'x86_64','pie':True,'stripped':False,
                         'source_sha256':sha(work/'abi.c'),'binary_sha256':sha(work/'original')}
        outputs=[]
        if args.resource=='gtirb-rewriting':
            run([prefix/'lib/python/ddisasm/ddisasm',work/'original','--ir',work/'input.gtirb','-j1'],'disassemble')
            run([sys.executable,prefix/'tools/nop_pass.py',work/'input.gtirb',work/'patched.gtirb',work/'patch.json'],'nop-patch')
            patch=json.loads((work/'patch.json').read_text())
            require(patch['insertions']>=2 and patch['bytes_after']>patch['bytes_before'],'No effective insertion')
            run([prefix/'lib/python/gtirb_pprinter/gtirb-pprinter','--policy=complete',work/'patched.gtirb','-b',work/'rewritten'],'reassemble')
            disassembly=run(['objdump','-d',work/'rewritten'],'disassembly').stdout.decode()
            require('<fold>:' in disassembly and '<main>:' in disassembly,'ABI symbol lost')
            for name in ['fold','main']:
                first=disassembly.split('<'+name+'>:',1)[1].splitlines()[1]
                require('nop' in first,'NOP missing at function '+name)
            result['transformation']=patch
            result['abi']={'convention':'SysV AMD64','integer_arguments':8,'register_arguments':6,
                           'stack_arguments':2,'return_value':'long','symbols':['fold','main'],
                           'entry_nop_verified':True,'clobbers':[]}
        elif args.resource=='retrowrite':
            run([sys.executable,prefix/'src/retrowrite/retrowrite',work/'original',work/'rewritten.s'],'symbolize')
            assembly=(work/'rewritten.s').read_text()
            require(len(assembly)>1000 and '.globl' in assembly and 'fold' in assembly,'Missing symbolic assembly')
            run(['gcc',work/'rewritten.s','-pie','-o',work/'rewritten'],'reassemble')
            result['transformation']={'symbolic_assembly_sha256':sha(work/'rewritten.s'),
                 'architecture_scope':'x86_64 only','pie_required':True,'symbol_table_required':True,
                 'cpp_qualified':False,'asan_or_afl_instrumentation_qualified':False}
        elif args.resource=='revng':
            # The distribution-specific pipeline is installed with its original payload.
            run([sys.executable,prefix/'tools/revng_lift.py',prefix,work], 'lift',timeout=600)
            detail=json.loads((work/'revng-result.json').read_text())
            require(detail['status']=='passed','rev.ng lift failed')
            result['transformation']=detail
        else:
            run([sys.executable,prefix/'tools/mctoll_lift.py',prefix,work], 'lift',timeout=300)
            detail=json.loads((work/'mctoll-result.json').read_text())
            require(detail['status']=='passed','mctoll lift failed')
            result['transformation']=detail
        if args.resource in {'gtirb-rewriting','retrowrite'}:
            inputs=[-100000,-17,-1,0,1,7,19,59,12345,100000]
            for index,value in enumerate(inputs):
                before=run([work/'original',value],f'original-{index:02d}')
                after=run([work/'rewritten',value],f'rewritten-{index:02d}')
                expected=reference(value).encode()
                require(before.stdout==after.stdout==expected and before.stderr==after.stderr==b'',
                        f'Behavior mismatch at {value}')
                outputs.append({'input':value,'expected':expected.decode().strip(),'original':before.stdout.decode().strip(),
                                'rewritten':after.stdout.decode().strip(),'returncodes':[before.returncode,after.returncode]})
            result['execution_cases']=outputs
            require(sha(work/'original')!=sha(work/'rewritten'),'Rewriting did not produce a distinct binary')
            for name in ['original','rewritten']:
                result['files'][name]={'sha256':sha(work/name),'bytes':(work/name).stat().st_size}
        result['status']='passed'
    except Exception as error:
        result['status']='failed';result['error']=repr(error)
        (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
        raise
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('CPG_RESOURCE_CHECK_PASSED '+json.dumps(result),flush=True)

if __name__=='__main__':
    main()
