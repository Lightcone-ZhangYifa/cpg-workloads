#!/usr/bin/env python3
"""Exercise the pinned upstream generator, verifier and a bounded real rewrite."""
import argparse,json,pathlib,subprocess,tempfile,time,resource,sys
if sys.flags.optimize:raise RuntimeError('Functional qualification requires Python optimization disabled')
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=pathlib.Path(__file__).resolve().parent;prefix=pathlib.Path(a.prefix).resolve();src=pathlib.Path(a.source).resolve();out=pathlib.Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
rows=[]
def run(name,argv,expected=0):
 start=time.monotonic();r=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=90)
 (out/(name+'.stdout')).write_text(r.stdout);(out/(name+'.stderr')).write_text(r.stderr)
 rows.append({'id':name,'argv':[str(x) for x in argv],'returncode':r.returncode,'expected':'nonzero' if expected is None else expected,'seconds':time.monotonic()-start})
 (out/'commands.json').write_text(json.dumps(rows,indent=2)+'\n')
 assert (r.returncode!=0 if expected is None else r.returncode==expected),(name,r.stderr[-2500:])
 return r.stdout,r.stderr
example=prefix/'bin/llvm-dialects-example';gen=prefix/'bin/llvm-dialects-tblgen';rewrite=prefix/'bin/cpg-dialects-rewrite'
built,_=run('upstream-builder',[example]);assert '@xd.ir.add32' in built
f=out/'built.ll';f.write_text(built)
run('parse-verify-builder',[example,'-verify',f])
bad,_=run('upstream-seven-verifier-errors',[example,'-verify',src/'test/example/verifier-basic.ll'],None);assert bad.count('Verifier error in:')==7
for case,dialect,mode,fail in [('duplicate-ops','dups','defs',True),('no-type-result','test','defs',True),('vararg-non-tail-pos','test','defs',True),('superclass-vararg','test','decls',True),('no-or-capture.test','test','defs',True),('single-vararg','test','decls',False),('logic-or-free-variables','test','defs',False)]:
 text,err=run('upstream-tablegen-'+case,[gen,'-gen-dialect-'+mode,'-dialect='+dialect,'-I',src/'include',src/('test/tablegen/'+case+'.td')],None if fail else 0)
 if fail: assert err or text
 else: assert len(text)>200
rewritten,diagnostic=run('bounded-add32-rewrite',[rewrite,root/'dialect-input.ll'])
assert 'changed=1 comparisons=14 negative_preserved=1' in diagnostic
assert rewritten.count('call i32 @xd.ir.add32')==1 and 'i32 7)' in rewritten
r=out/'rewritten.ll';r.write_text(rewritten);run('parse-verify-rewritten',[example,'-verify',r])
mut=out/'mutated-precondition.ll';mut.write_text((root/'dialect-input.ll').read_text().replace('i32 0, i32 0)','i32 0, i32 1)',1))
run('rewrite-precondition-negative',[rewrite,mut],None)
invalid=out/'invalid.ll';invalid.write_text('define broken {');run('parse-negative',[example,'-verify',invalid],None)
summary={'status':'passed','commit':'4d0dfd05c436ea49aaaa6ad010bb3cf64da0ddb9','llvm_pair':'23.1.4','commands':len(rows),'upstream_tablegen_cases':7,'upstream_verifier_diagnostics':7,'rewrite_comparisons':14,'rewrite_changes':1,'negative_precondition_preserved':True,'limits':['Standalone direct C++ build of unmodified upstream sources; upstream full CMake/lit/gtest matrix not run','LLVM SDK subset uses explicit shared host zstd/xml2 binding','Add32 semantics interpreter is a bounded CPG fixture, not a general LLVM interpreter or proof']}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
