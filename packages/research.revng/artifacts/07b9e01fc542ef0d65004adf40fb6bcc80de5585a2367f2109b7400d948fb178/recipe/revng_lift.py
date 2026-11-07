#!/usr/bin/env python3
"""Run the bounded rev.ng x86-64 ELF lift using the isolated bundled runtime."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys

prefix=Path(sys.argv[1]).resolve();work=Path(sys.argv[2]).resolve();runtime=prefix/'runtime'
python=runtime/'bin/python3.14';revng=runtime/'bin/revng';llvm=runtime/'lib64/llvm/llvm/bin'
env={**os.environ,'PYTHONPATH':str(runtime/'lib64/python3.14/site-packages'),
     'LD_LIBRARY_PATH':':'.join(str(p) for p in [runtime/'lib64',runtime/'lib64/llvm/llvm/lib']),
     'PATH':str(runtime/'bin')+':'+str(llvm)+':'+os.environ.get('PATH','/usr/bin:/bin'),
     'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','LC_ALL':'C','OMP_NUM_THREADS':'1',
     'XDG_CACHE_HOME':str(work/'cache'),'XDG_CONFIG_HOME':str(work/'config')}
env.pop('PYTHONHOME',None)
result={'status':'running','commands':[],'qualification':'x86_64 ELF lifting and CFG only; no recompilation or equivalence claim'}
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(c,m):
    if not c:raise RuntimeError(m)
def run(argv,name):
    x=subprocess.run(list(map(str,argv)),cwd=work,env=env,capture_output=True,timeout=600)
    for ext,data in [('stdout',x.stdout),('stderr',x.stderr)]:(work/(name+'.'+ext)).write_bytes(data)
    result['commands'].append({'name':name,'argv':list(map(str,argv)),'returncode':x.returncode,
      'stdout':name+'.stdout','stderr':name+'.stderr','stdout_sha256':sha(work/(name+'.stdout')),
      'stderr_sha256':sha(work/(name+'.stderr'))})
    require(x.returncode==0,name+' returned '+str(x.returncode)+': '+x.stderr.decode(errors='replace')[-3000:])
    return x
try:
    project=work/'project';require(not project.exists(),'Project must be freshly created');project.mkdir()
    command=[python,revng,'-C',project,'project']
    run(command+['init',work/'original','--no-initial-auto-analysis'],'revng-init')
    run(command+['analyze','parse-binary','-o','/dev/null'],'revng-parse')
    run(command+['artifact','lift','-o',work/'lifted.bc'],'revng-lift')
    run(command+['artifact','disassemble','fold','-o',work/'fold.ptml'],'revng-disassemble')
    run([llvm/'llvm-dis',work/'lifted.bc','-o',work/'lifted.ll'],'llvm-dis')
    run([llvm/'opt','-passes=verify','-disable-output',work/'lifted.bc'],'llvm-verify')
    convert='import json,sys,yaml;json.dump(yaml.safe_load(open(sys.argv[1])),open(sys.argv[2],"w"),indent=2)'
    run([python,'-c',convert,project/'revng.yml',work/'model.json'],'parse-model')
    model=json.loads((work/'model.json').read_text())
    require(model['Architecture']=='x86_64' and model['DefaultABI']=='SystemV_x86_64','Unexpected model target')
    require(model['Binaries'][0]['Hash']==sha(work/'original'),'Model does not identify current input')
    functions={f['Name']:f for f in model['Functions'] if 'Name' in f}
    require({'fold','main'}<=set(functions),'Controlled function names absent from model')
    fold=functions['fold']['Entry'];require(fold.endswith(':Code_x86_64'),'Invalid fold address kind')
    ir=(work/'lifted.ll').read_text();ptml=(work/'fold.ptml').read_text()
    require('target triple = "x86_64-unknown-linux-gnu"' in ir,'Wrong LLVM target triple')
    require('define void @root(' in ir and '@newpc(' in ir,'Missing lifted root or PC annotations')
    branches=len(re.findall(r'\bbr\s+i1\s',ir));blocks=ptml.count('data-scope="asm.basic-block"')
    require(branches>=2 and blocks>=3,'Insufficient real branch/basic-block structure')
    require('/function/'+fold in ptml,'CFG does not identify model fold entry')
    # Validate normalized model address against the original ELF symbol and first
    # load segment. PIE in this fixture starts at virtual address/file offset 0.
    symbols=(work/'symbols.stdout').read_text()
    match=re.search(r'^\s*\d+:\s+([0-9a-fA-F]+)\s+\d+\s+FUNC\s+\S+\s+\S+\s+\S+\s+fold\s*$',symbols,re.M)
    require(match is not None,'Original fold symbol missing')
    base=min(int(s['StartAddress'].split(':')[0],16) for s in model['Segments'])
    require(int(fold.split(':')[0],16)==base+int(match.group(1),16),'Model/ELF fold address mismatch')
    plain=html.unescape(re.sub('<[^>]+>','',ptml))
    require('ret' in plain and ('cmp' in plain or 'test' in plain),'Missing return/conditional test in recovered CFG')
    result.update({'status':'passed','architecture':model['Architecture'],'abi':model['DefaultABI'],
      'entry_point':model['EntryPoint'],'fold_entry':fold,'fold_basic_blocks':blocks,
      'conditional_llvm_branches':branches,'model_function_count':len(model['Functions']),
      'input_sha256':sha(work/'original'),'normalized_image_base':hex(base),
      'files':{name:{'sha256':sha(work/name),'bytes':(work/name).stat().st_size} for name in ['lifted.bc','lifted.ll','fold.ptml','model.json']},
      'model_yaml':{'sha256':sha(project/'revng.yml'),'bytes':(project/'revng.yml').stat().st_size},
      'omitted_domains':['IDA database import','other target architectures','recompilation','UI','network services']})
except Exception as error:
    result['status']='failed';result['error']=repr(error);(work/'revng-result.json').write_text(json.dumps(result,indent=2)+'\n');raise
(work/'revng-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
