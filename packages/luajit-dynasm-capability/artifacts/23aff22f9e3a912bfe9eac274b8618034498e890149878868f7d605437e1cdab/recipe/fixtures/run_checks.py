#!/usr/bin/env python3
"""Relocatable functional profile. No network or writes to the package prefix."""
import json, pathlib, platform, subprocess, tempfile

PREFIX=pathlib.Path(__file__).resolve().parent
NAME=json.loads((PREFIX/'cpg-resource.json').read_text())['name']
if platform.system()!='Linux' or platform.machine()!='x86_64':
    raise SystemExit('This profile is qualified only for Linux x86_64 SysV.')
checks=[]
def run(args,expected):
    p=subprocess.run([str(a) for a in args],text=True,capture_output=True,timeout=120)
    if p.returncode or expected not in p.stdout:
        raise RuntimeError(json.dumps({'argv':[str(a) for a in args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'expected':expected}))
    checks.append({'argv':[str(a) for a in args],'stdout':p.stdout,'expected':expected,'exit_code':0})

fixtures=PREFIX/'share'/NAME/'cpg-fixtures'
if NAME=='asmjit':run([PREFIX/'bin/cpg-asmjit-check'],'ASMJIT_PASS')
elif NAME=='xbyak':run([PREFIX/'bin/cpg-xbyak-check'],'XBYAK_PASS')
elif NAME=='sljit':
    for name,value in [('first_program',15),('branch',6),('func_call',7)]:
        run([PREFIX/'bin'/('sljit-'+name)],f'func return {value}')
elif NAME=='lightning':
    for n,value in [(0,1),(1,1),(5,120),(10,3628800)]:
        run([PREFIX/'bin/cpg-lightning-factorial',n],f'factorial({n}) = {value}')
elif NAME=='tinycc':
    run([PREFIX/'bin/cpg-libtcc-check',PREFIX/'lib/tcc'],'LIBTCC_PASS')
    with tempfile.TemporaryDirectory(prefix='cpg-tinycc-functional-') as temp:
        output=pathlib.Path(temp)/'fixture'
        run([PREFIX/'bin/tcc',fixtures/'tcc_elf_check.c','-o',output],'')
        if output.read_bytes()[:4]!=b'\x7fELF':raise RuntimeError('Output did not contain an ELF header')
        run([output],'TCC_ELF_PASS sum=499500')
elif NAME=='luajit':
    run([PREFIX/'bin/cpg-frozen-luajit-check',fixtures/'luajit_ffi_trace.lua'],'LUAJIT_TRACE_PASS')
    run([PREFIX/'bin/cpg-dynasm-check'],'DYNASM_PASS')
    run([PREFIX/'bin/luajit','-e',"require('jit.v'); assert(6*7==42); print('LUAJIT_RELOCATED_PASS')"],'LUAJIT_RELOCATED_PASS')
    with tempfile.TemporaryDirectory(prefix='cpg-dynasm-preprocess-') as temp:
        output=pathlib.Path(temp)/'generated.c'
        run([PREFIX/'bin/luajit',PREFIX/'share/luajit/source/dynasm/dynasm.lua','-o',output,fixtures/'dynasm_check.dasc'],'')
        text=output.read_text()
        if 'dasm_put' not in text or 'cpg_actions' not in text:raise RuntimeError('DynASM preprocessing did not emit expected C API')
else:raise RuntimeError('Unknown profile '+NAME)
print(json.dumps({'schema_version':1,'resource':NAME,'status':'passed','host':platform.platform(),'network_used':False,'checks':checks},indent=2))
