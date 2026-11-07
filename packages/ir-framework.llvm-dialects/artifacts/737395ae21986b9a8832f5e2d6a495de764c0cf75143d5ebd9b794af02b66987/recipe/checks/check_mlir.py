#!/usr/bin/env python3
"""Bounded MLIR 23.1.4 IRDL / PDLL / ODS check using only local inputs."""
import argparse,json,pathlib,subprocess,time,sys
if sys.flags.optimize:raise RuntimeError('Functional qualification requires Python optimization disabled')
p=argparse.ArgumentParser();p.add_argument('--tools',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=pathlib.Path(__file__).resolve().parent;tools=pathlib.Path(a.tools).resolve();out=pathlib.Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
rows=[]
def run(name,argv,*,text=None,expected=0):
 start=time.monotonic();r=subprocess.run([str(x) for x in argv],input=text,capture_output=True,text=True,timeout=120)
 (out/(name+'.stdout')).write_text(r.stdout);(out/(name+'.stderr')).write_text(r.stderr)
 rows.append({'id':name,'argv':[str(x) for x in argv],'returncode':r.returncode,'expected':'nonzero' if expected is None else expected,'seconds':time.monotonic()-start})
 (out/'commands.json').write_text(json.dumps(rows,indent=2)+'\n')
 assert (r.returncode!=0 if expected is None else r.returncode==expected),(name,r.stderr[-3000:])
 return r.stdout,r.stderr
opt=tools/'bin/mlir-opt';pdll=tools/'bin/mlir-pdll';tblgen=tools/'bin/mlir-tblgen';irdl=root/'mlir/rules.irdl.mlir'
v,_=run('version',[opt,'--version']);assert '23.1.4' in v
run('irdl-definition',[opt,irdl])
original=(root/'mlir/input.mlir').read_text()
valid,_=run('irdl-positive',[opt,'--irdl-file='+str(irdl)],text=original)
again,_=run('irdl-roundtrip',[opt,'--irdl-file='+str(irdl)],text=valid);assert again==valid
bad=original.replace('(i32) -> i32','(i32) -> i64',1).replace('%r : i32','%r : i64',1).replace('@positive(%arg: i32) -> i32','@positive(%arg: i32) -> i64')
_,diag=run('irdl-wrong-result-rejected',[opt,'--irdl-file='+str(irdl)],text=bad,expected=None);assert 'error:' in diag and ('i32' in diag or 'constraint' in diag)
pdl,_=run('pdll-to-pdl',[pdll,'-x=mlir',root/'mlir/identity.pdll']);assert 'pdl.pattern @RemoveIdentity' in pdl
cpp,_=run('pdll-to-cpp',[pdll,'-x=cpp',root/'mlir/identity.pdll']);assert 'populateGeneratedPDLLPatterns' in cpp
run('pdll-invalid-rejected',[pdll,'-x=mlir'],text='Pattern Broken { replace op<cpg.identity> with missing; }',expected=None)
combined=pdl.replace('module {','module @patterns {',1)+'\n'+original
(out/'combined.mlir').write_text(combined)
transformed,_=run('pdl-actual-rewrite',[opt,'--irdl-file='+str(irdl),'--test-pdl-bytecode-pass'],text=combined)
assert '"cpg.identity"' not in transformed
assert 'arith.addi' in transformed and '@negative_no_match' in transformed and '@positive' in transformed
run('rewritten-verified',[opt,'--irdl-file='+str(irdl)],text=transformed)
decls,_=run('ods-declarations',[tblgen,root/'mlir/cpg.td','-I',tools/'include','-gen-op-decls']);assert 'IdentityOp' in decls
defs,_=run('ods-definitions',[tblgen,root/'mlir/cpg.td','-I',tools/'include','-gen-op-defs']);assert 'IdentityOp' in defs
summary={'status':'passed','version':'23.1.4','original_pin':'7a941dfb2877a0b8cf30323fefa85ad019e0b0f5','commands':len(rows),'checks':['IRDL operation registration','positive type verification','fresh parse-print roundtrip','wrong-result-type rejection','PDLL to PDL and C++ generation','invalid PDLL rejection','generated PDL applied by upstream bytecode test pass','nonmatching arith operation retained','transformed IR verified','ODS C++ declarations and definitions generated'],'limits':['Official prebuilt tools; no local LLVM source build','PDL exercised through upstream test-pdl-bytecode-pass driver','C++ generated text checked; not compiled as a new plugin','No general semantic equivalence proof or performance claim']}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
