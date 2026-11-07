#!/usr/bin/env python3
"""Fresh bounded x86-64 C ELF -> raised LLVM IR -> rebuilt execution check."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import uuid

FIXTURE=r'''int main(int argc, char **argv) {
  int n = argc - 1;
  int total = 11;
  for (int i = 0; i < n; ++i) {
    if (i & 1) total += i * 3 + 1;
    else total += i * 5 + 2;
  }
  if (n > 8) total -= 7;
  return total & 255;
}
'''
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(condition,message):
    if not condition:raise RuntimeError(message)
def oracle(n):
    return (11+sum(i*3+1 if i&1 else i*5+2 for i in range(n))-(7 if n>8 else 0))&255
def main():
    p=argparse.ArgumentParser();p.add_argument('resource');p.add_argument('prefix',type=Path);p.add_argument('build',type=Path)
    args=p.parse_args();prefix=args.prefix.resolve();args.build.mkdir(parents=True,exist_ok=True)
    nonce=uuid.uuid4().hex;work=Path(tempfile.mkdtemp(prefix='semantic-'+nonce[:12]+'-',dir=args.build)).resolve()
    result={'schema_version':1,'resource':'llvm-mctoll','nonce':nonce,'status':'running','prefix':str(prefix),'work':str(work),'commands':[]}
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','LC_ALL':'C','OMP_NUM_THREADS':'1'}
    # Use the paired LLVM runtime in this prefix. Never mix in rev.ng's LLVM16.
    env['LD_LIBRARY_PATH']=str(prefix/'lib')
    env['PATH']=str(prefix/'bin')+':'+os.environ.get('PATH','/usr/bin:/bin')
    def run(argv,name,expected=0,timeout=180):
        argv=list(map(str,argv));x=subprocess.run(argv,cwd=work,env=env,capture_output=True,timeout=timeout)
        for label,data in [('stdout',x.stdout),('stderr',x.stderr)]:(work/(name+'.'+label)).write_bytes(data)
        result['commands'].append({'name':name,'argv':argv,'returncode':x.returncode,
            'stdout':name+'.stdout','stderr':name+'.stderr','stdout_sha256':sha(work/(name+'.stdout')),
            'stderr_sha256':sha(work/(name+'.stderr'))})
        require(x.returncode==expected,f'{name} returned {x.returncode}, expected {expected}: '+x.stderr.decode(errors='replace')[-2500:])
        return x
    try:
        inventory=json.loads((prefix/'INVENTORY.json').read_text())
        for row in inventory:
            f=prefix/row['path'];require(f.is_file() and f.stat().st_size==row['bytes'] and sha(f)==row['sha256'],'Installed payload changed: '+row['path'])
        result['installed_files_verified']=len(inventory)
        source=work/'bounded.c';source.write_text(FIXTURE)
        run(['gcc','-O0','-no-pie','-fno-pie','-fno-stack-protector','-fcf-protection=none',source,'-o',work/'original'],'compile-original')
        data=(work/'original').read_bytes()
        require(data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',data,16)[0]==2 and struct.unpack_from('<H',data,18)[0]==62,'Expected non-PIE x86-64 ELF64')
        run(['readelf','--syms','--wide',work/'original'],'original-symbols')
        run([prefix/'bin/llvm-mctoll','--version'],'mctoll-version')
        version=run([prefix/'bin/opt','--version'],'paired-opt-version')
        require('15.0.7' in version.stdout.decode(),'Unexpected opt version')
        version=run([prefix/'bin/clang','--version'],'paired-clang-version')
        require('15.0.7' in version.stdout.decode(),'Unexpected clang version')
        linked=run(['ldd',prefix/'libexec/llvm-mctoll'],'runtime-dependencies').stdout.decode()
        require('not found' not in linked and str(prefix/'lib/libLLVM-15.so.1') in linked and str(prefix/'lib/libclang-cpp.so.15') in linked,'Paired libraries did not resolve inside independent prefix')
        run([prefix/'bin/llvm-mctoll','-d',work/'original'],'raise')
        ir=work/'original-dis.ll';require(ir.is_file() and ir.stat().st_size>100,'No fresh LLVM IR')
        text=ir.read_text();target_match=re.search(r'^target triple = "([^"]+)"',text,re.M)
        require(target_match is None or target_match.group(1).startswith('x86_64'),'Unexpected emitted target triple')
        require(re.search(r'define\s+[^\n]*@main\(',text),'Raised main missing')
        require(re.search(r'br\s+i1\s',text),'Conditional control flow not raised')
        run([prefix/'bin/opt','-passes=verify','-disable-output',ir],'llvm-verify')
        run([prefix/'bin/clang','-target','x86_64-pc-linux-gnu','-O0','-no-pie',ir,'-o',work/'rebuilt'],'compile-raised')
        rebuilt_elf=(work/'rebuilt').read_bytes()
        require(rebuilt_elf[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',rebuilt_elf,18)[0]==62,'Rebuilt ELF has incorrect architecture')
        cases=[]
        for n in [0,1,2,3,4,7,8,9,12,19,31]:
            expected=oracle(n);arguments=['owned-argument']*n
            before=run([work/'original',*arguments],f'original-{n:02d}',expected)
            after=run([work/'rebuilt',*arguments],f'rebuilt-{n:02d}',expected)
            require(before.stdout==after.stdout==b'' and before.stderr==after.stderr==b'','Unexpected output')
            cases.append({'argument_count':n,'expected_returncode':expected,'original_returncode':before.returncode,'rebuilt_returncode':after.returncode})
        require(sha(work/'original')!=sha(work/'rebuilt'),'No distinct rebuilt executable')
        result.update({'status':'passed','input':{'architecture':'x86_64','format':'ELF64','pie':False,'language':'C','source_sha256':sha(source)},
          'execution_cases':cases,'ir':{'sha256':sha(ir),'bytes':ir.stat().st_size,'emitted_target_triple':target_match.group(1) if target_match else None,'explicit_recompile_target':'x86_64-pc-linux-gnu','verifier':'paired LLVM 15.0.7 opt','conditional_branches':len(re.findall(r'br\s+i1\s',text))},
          'files':{n:{'sha256':sha(work/n),'bytes':(work/n).stat().st_size} for n in ['original','rebuilt']},
          'qualification_boundary':'Supported scalar integer C, argc input, loop and branches, Linux x86_64 SysV; no libc call, C++, vector, Windows, ARM or RISC-V qualification'})
    except Exception as error:
        result['status']='failed';result['error']=repr(error);(work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);raise
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('CPG_RESOURCE_CHECK_PASSED '+json.dumps(result),flush=True)
if __name__=='__main__':main()
