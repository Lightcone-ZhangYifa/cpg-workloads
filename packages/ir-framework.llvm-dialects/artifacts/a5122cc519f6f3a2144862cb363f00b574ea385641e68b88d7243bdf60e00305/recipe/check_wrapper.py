"""CPG checks write evidence only outside installed prefixes."""
from pathlib import Path
import hashlib,json,subprocess,sys,tempfile
if sys.flags.optimize:
 raise RuntimeError('Qualification checks require Python assertions enabled; optimization is not allowed')
mode=sys.argv[1];prefix=Path(sys.argv[2]).resolve();build=Path(sys.argv[3]).resolve();build.mkdir(parents=True,exist_ok=True)
out=Path(tempfile.mkdtemp(prefix='worker007-'+mode+'-',dir=build))/'evidence'
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while b:=f.read(1024*1024):h.update(b)
 return h.hexdigest()
if mode=='dialects':
 subprocess.run([sys.executable,prefix/'checks/check_dialects.py','--prefix',prefix,'--source',prefix/'share/llvm-dialects','--output',out],check=True)
elif mode=='mlir':
 tools=Path(sys.argv[4]).resolve();lock=json.loads((prefix/'tools-lock.json').read_text())
 for row in lock['files']:
  path=tools/row['path']
  if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:raise RuntimeError('LLVM dependency integrity mismatch: '+row['path'])
 subprocess.run([sys.executable,prefix/'checks/check_mlir.py','--tools',tools,'--output',out],check=True)
elif mode=='reference':
 lock=json.loads((prefix/'reference-lock.json').read_text());count=0
 for row in lock['files']:
  path=prefix/row['path']
  if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:raise RuntimeError('MLIR reference integrity mismatch: '+row['path'])
  count+=1
 if not (prefix/'source/mlir/examples/toy').is_dir():raise RuntimeError('Missing original MLIR Toy examples')
 subprocess.run([sys.executable,prefix/'query_reference.py','--query','PDLL','--limit','3'],check=True)
 print(json.dumps({'status':'passed','kind':'availability','files_verified':count,'original_pin':lock['original_pin'],'functional_execution_is_separate':True}))
else:raise ValueError(mode)
