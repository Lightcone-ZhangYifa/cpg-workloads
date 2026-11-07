#!/usr/bin/env python3
"""Bounded CPU-only functional checks; failures are explicit under python -O."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, struct, subprocess, tempfile, time

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

VALID = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main"
OpExecutionMode %main LocalSize 1 1 1
%void = OpTypeVoid
%uint = OpTypeInt 32 0
%u1 = OpConstant %uint 1
%function = OpTypeFunction %void
%main = OpFunction %void None %function
%label = OpLabel
%sum = OpIAdd %uint %u1 %u1
OpReturn
OpFunctionEnd
'''

OPENCL = '''__kernel void affine(__global int *out, __global const int *input, int bias) {
    size_t i = get_global_id(0);
    out[i] = input[i] * 3 + bias;
}
__kernel void sum_pair(__global float *out, __global const float *input) {
    out[0] = input[0] + input[1];
}
'''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('resource', choices=['spirv-tools','spirv-llvm-translator'])
    ap.add_argument('--prefix',type=pathlib.Path,required=True)
    ap.add_argument('--validator-prefix',type=pathlib.Path)
    ap.add_argument('--output',type=pathlib.Path)
    args=ap.parse_args()
    prefix=args.prefix.resolve()
    output=args.output or pathlib.Path(tempfile.mkdtemp(prefix='cpg-worker042-check-',dir=pathlib.Path.cwd()))
    output.mkdir(parents=True,exist_ok=True)
    output=output.resolve()
    report={'resource':args.resource,'prefix':str(prefix),'output':str(output),'schema_version':1,
            'scope':'CPU-only artifact validation; no GPU execution, benchmark, or optimization equivalence claim',
            'commands':[],'checks':[],'status':'running'}
    def publish():
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    def run(name, argv, expected=0, regex=None):
        started=time.time()
        p=subprocess.run([str(x) for x in argv],cwd=output,text=True,capture_output=True,timeout=120)
        (output/(name+'.stdout')).write_text(p.stdout)
        (output/(name+'.stderr')).write_text(p.stderr)
        row={'name':name,'argv':[str(x) for x in argv],'returncode':p.returncode,
             'seconds':round(time.time()-started,3),'expected':expected,'stdout_sha256':sha(output/(name+'.stdout')),
             'stderr_sha256':sha(output/(name+'.stderr'))}
        report['commands'].append(row); publish()
        require((p.returncode==expected) if expected is not None else p.returncode!=0,
                name+': unexpected return code '+str(p.returncode)+' '+p.stderr[:2000])
        if regex is not None:
            import re
            require(re.search(regex,p.stdout+p.stderr,re.I|re.S) is not None,name+': diagnostic pattern missing')
        return p
    def check(name, ok):
        report['checks'].append({'name':name,'passed':bool(ok)}); publish();require(ok,name)
    def exe(name):
        root=args.validator_prefix.resolve() if args.validator_prefix and name in ('spirv-val','spirv-dis','spirv-as','spirv-opt') else prefix
        p=root/'bin'/name
        require(p.is_file(), 'missing program '+str(p))
        return p
    try:
        if args.resource=='spirv-tools':
            for name in ('spirv-as','spirv-dis','spirv-val','spirv-opt'):
                run('version-'+name,[exe(name),'--version'],regex='SPIRV-Tools')
            (output/'valid.spvasm').write_text(VALID)
            run('assemble-valid',[exe('spirv-as'),'--target-env','spv1.0','valid.spvasm','-o','valid.spv'])
            run('validate-valid',[exe('spirv-val'),'--target-env','vulkan1.0','valid.spv'])
            data=(output/'valid.spv').read_bytes()
            check('binary-magic-version-alignment',len(data)%4==0 and len(data)>=20 and struct.unpack('<II',data[:8])==(0x07230203,0x10000))
            run('disassemble-valid',[exe('spirv-dis'),'--no-header','valid.spv','-o','dis.spvasm'])
            run('assemble-roundtrip',[exe('spirv-as'),'--target-env','spv1.0','dis.spvasm','-o','roundtrip.spv'])
            run('validate-roundtrip',[exe('spirv-val'),'--target-env','vulkan1.0','roundtrip.spv'])
            check('assembly-roundtrip-byte-identical',data==(output/'roundtrip.spv').read_bytes())
            (output/'bad-type.spvasm').write_text(VALID.replace('OpIAdd %uint %u1 %u1','OpFAdd %uint %u1 %u1'))
            run('assemble-bad-type',[exe('spirv-as'),'--target-env','spv1.0','bad-type.spvasm','-o','bad-type.spv'])
            run('reject-bad-type',[exe('spirv-val'),'--target-env','vulkan1.0','bad-type.spv'],expected=None,regex='(floating|float).*(type|Type)')
            (output/'bad-id.spvasm').write_text(VALID.replace('OpIAdd %uint %u1 %u1','OpIAdd %uint %not_defined %u1'))
            run('assemble-bad-id',[exe('spirv-as'),'--target-env','spv1.0','bad-id.spvasm','-o','bad-id.spv'])
            run('reject-bad-id',[exe('spirv-val'),'--target-env','vulkan1.0','bad-id.spv'],expected=None,regex='(not been defined|undefined)')
            (output/'truncated.spv').write_bytes(data[:-1])
            run('reject-truncated',[exe('spirv-val'),'truncated.spv'],expected=None,regex='(size|word|binary)')
            run('optimizer-strip-debug',[exe('spirv-opt'),'--strip-debug','valid.spv','-o','optimized.spv'])
            run('validate-optimizer-output',[exe('spirv-val'),'--target-env','vulkan1.0','optimized.spv'])
            report['optimizer_semantic_equivalence']='not_tested'
        else:
            for name in ('clang-18','llvm-spirv','llvm-dis','opt'):
                run('version-'+name,[exe(name),'--version'])
            (output/'kernels.cl').write_text(OPENCL)
            run('clang-opencl',[exe('clang-18'),'-cc1','-triple','spir64-unknown-unknown','-cl-std=CL2.0','-finclude-default-header','-emit-llvm-bc','-O1','-x','cl','kernels.cl','-o','kernels.bc'])
            run('llvm-input-verify',[exe('opt'),'-passes=verify','-disable-output','kernels.bc'])
            run('translate-forward',[exe('llvm-spirv'),'--spirv-max-version=1.2','kernels.bc','-o','kernels.spv'])
            run('validate-opencl',[exe('spirv-val'),'--target-env','opencl2.2','kernels.spv'])
            run('disassemble-opencl',[exe('spirv-dis'),'kernels.spv','-o','kernels.spvasm'])
            s=(output/'kernels.spvasm').read_text()
            check('kernel-capability', 'OpCapability Kernel' in s)
            check('physical64-opencl-memory-model','OpMemoryModel Physical64 OpenCL' in s)
            check('two-kernel-entrypoints',s.count('OpEntryPoint Kernel')==2 and '"affine"' in s and '"sum_pair"' in s)
            run('translate-reverse',[exe('llvm-spirv'),'-r','kernels.spv','-o','reverse.bc'])
            run('llvm-reverse-verify',[exe('opt'),'-passes=verify','-disable-output','reverse.bc'])
            run('llvm-reverse-dis',[exe('llvm-dis'),'reverse.bc','-o','reverse.ll'])
            ll=(output/'reverse.ll').read_text()
            check('reverse-kernel-signatures','spir_kernel void @affine(' in ll and 'spir_kernel void @sum_pair(' in ll)
            check('reverse-global-address-space','addrspace(1)' in ll)
            run('translate-roundtrip',[exe('llvm-spirv'),'--spirv-max-version=1.2','reverse.bc','-o','roundtrip.spv'])
            run('validate-roundtrip-opencl',[exe('spirv-val'),'--target-env','opencl2.2','roundtrip.spv'])
            run('disassemble-roundtrip',[exe('spirv-dis'),'roundtrip.spv','-o','roundtrip.spvasm'])
            rt=(output/'roundtrip.spvasm').read_text()
            check('roundtrip-two-kernel-entrypoints',rt.count('OpEntryPoint Kernel')==2 and '"affine"' in rt and '"sum_pair"' in rt)
            (output/'broken.bc').write_bytes(b'not LLVM bitcode')
            run('reject-non-bitcode',[exe('llvm-spirv'),'broken.bc','-o','should-not-exist.spv'],expected=None,regex='(bitcode|Invalid|expected)')
            report['roundtrip_semantics']='Structure, types, entrypoints and LLVM verifier checked; byte identity and semantic equivalence not asserted.'
        report['status']='passed'
        report['outputs']=[{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file() and p.name!='report.json']
        publish();print(json.dumps({'status':'passed','resource':args.resource,'commands':len(report['commands']),'checks':len(report['checks']),'report':str(output/'report.json')}))
    except BaseException as e:
        report.update(status='failed',error=str(e));publish();raise

if __name__=='__main__': main()
