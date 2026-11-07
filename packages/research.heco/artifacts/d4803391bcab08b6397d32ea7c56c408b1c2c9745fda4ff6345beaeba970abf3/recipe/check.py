#!/usr/bin/env python3
"""Run actual HECO -> EmitC -> C++ -> SEAL with a separate integer oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback
import uuid

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):
            value.update(block)
    return value.hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--payload-lock-sha256')
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=True)
    pointer = base / 'last-result.json'
    pointer.unlink(missing_ok=True)
    out = base / ('check-' + uuid.uuid4().hex)
    out.mkdir()
    commands = []
    try:
        lock = prefix / 'PAYLOAD_LOCK.json'
        if args.payload_lock_sha256:
            require(digest(lock) == args.payload_lock_sha256, 'Payload lock differs from native package declaration')
        for row in json.loads(lock.read_text()):
            path = prefix / row['path']
            require(path.is_file() and path.stat().st_size == row['bytes'] and digest(path) == row['sha256'], 'Payload changed: ' + row['path'])
        # This self-tested kernel filter propagates to every compiler and runtime child.
        from offline import install
        policy = install()
        (out / 'offline-policy.json').write_text(json.dumps(policy, indent=2) + '\n')
        env = dict(os.environ, OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
        env.pop('LD_PRELOAD', None)
        env.pop('PYTHONPATH', None)
        env['LD_LIBRARY_PATH'] = str(prefix/'lib')
        def run(argv, label, expected_failure=False, timeout=180):
            start = time.monotonic()
            process = subprocess.run(list(map(str, argv)), cwd=out, env=env, text=True, capture_output=True, timeout=timeout)
            (out / (label + '.stdout')).write_text(process.stdout)
            (out / (label + '.stderr')).write_text(process.stderr)
            commands.append({'argv':list(map(str, argv)), 'label':label, 'returncode':process.returncode, 'duration_seconds':time.monotonic()-start, 'expected_failure':expected_failure})
            if expected_failure:
                require(process.returncode != 0, label + ' was unexpectedly accepted')
            else:
                require(process.returncode == 0, label + ' failed: ' + process.stderr[-3000:])
            return process
        shutil.copy2(prefix / 'fixtures/arithmetic.mlir', out / 'input.mlir')
        shutil.copy2(prefix / 'fixtures/driver.cpp', out / 'driver.cpp')
        heco = prefix / 'bin/heco'
        translate = prefix / 'bin/emitc-translate'
        compiler_version=run(['g++','--version'],'host-cxx-version').stdout
        heco_version=run([heco,'--version'],'heco-llvm-version').stdout
        for executable in [heco,translate]:
            dependency = run(['ldd',executable], 'dependencies-'+executable.name)
            require('not found' not in dependency.stdout, 'Missing runtime dependency')
            for line in dependency.stdout.splitlines():
                if 'libLLVM-' in line or 'libMLIR' in line:
                    require(str(prefix/'lib') in line, 'Compiler loaded SDK library outside its installed prefix')
        run([heco, '--mlir-disable-threading', '--fhe-pass', 'input.mlir', '-o', 'optimized.mlir'], 'optimize-fhe')
        run([heco, '--mlir-disable-threading', '--fhe2bfv=poly_mod_degree=4096', '--canonicalize', '--cse', 'optimized.mlir', '-o', 'bfv.mlir'], 'lower-bfv')
        # The unchanged upstream BFV printer emits its string parameter without
        # quotes. Retain its diagnostic snapshot, but use the supported in-memory
        # lowering pipeline instead of reparsing that intermediate serialization.
        run([heco, '--mlir-disable-threading', '--fhe2bfv=poly_mod_degree=4096', '--canonicalize', '--cse', '--bfv2emitc', '--canonicalize', '--cse', 'optimized.mlir', '-o', 'emitc.mlir'], 'lower-emitc')
        run([translate, '--mlir-to-cpp', 'emitc.mlir', '-o', 'generated.cpp'], 'translate-cpp')
        cpp = (out / 'generated.cpp').read_text()
        require(all(name in cpp for name in ['cpg_add', 'cpg_sub', 'cpg_muladd', 'evaluator_add', 'evaluator_sub', 'evaluator_multiply']), 'Generated C++ lacks expected functions/calls')
        require('assert(false)' not in cpp, 'Placeholder C++ is forbidden')
        run(['g++', '-std=c++17', '-O1', '-DNDEBUG', '-g0', 'driver.cpp', '-I' + str(prefix/'include/SEAL-4.0'), str(prefix/'lib/libseal-4.0.a'), '-pthread', '-o', 'encrypted-driver'], 'manual-cpp-build', timeout=300)
        cases = [([2,3,5,7], [11,13,17,19]), ([0,1,-1,65536], [9,0,2,65536]), ([-7,4,123,256], [6,-3,456,257])]
        modulus = 65537
        checked = []
        for index, (left, right) in enumerate(cases):
            process = run([out/'encrypted-driver', *left, *right], 'encrypted-case-' + str(index))
            observed = json.loads(process.stdout)
            require(observed['scheme'] == 'BFV' and observed['degree'] == 4096 and observed['plain_modulus'] == modulus and observed['security_level'] == 'tc128', 'Runtime parameters differ from declared test profile')
            reference = {'add':[(a+b)%modulus for a,b in zip(left,right)], 'sub':[(a-b)%modulus for a,b in zip(left,right)], 'muladd':[(a*b+a)%modulus for a,b in zip(left,right)]}
            require(len(observed['results']) == 3, 'Unexpected operation count')
            for row in observed['results']:
                require(row['values'] == reference[row['operation']], 'Independent plaintext mismatch in ' + row['operation'])
                require(row['noise_budget_bits'] > 0 and row['padding_zero'], 'Ciphertext validity or padding check failed')
            checked.append({'synthetic_inputs':[left,right], 'independent_reference':reference, 'observed':observed})
        require(len({json.dumps(row['independent_reference'],sort_keys=True) for row in checked}) == len(cases), 'Input variation did not produce distinct outputs')
        (out/'invalid.mlir').write_text('module { func.func @invalid() -> i32 { return %missing : i32 } }\n')
        invalid = run([heco, '--mlir-disable-threading', 'invalid.mlir', '-o', 'invalid-output.mlir'], 'invalid-ir', expected_failure=True)
        require('error:' in invalid.stderr, 'Invalid IR did not produce a compiler diagnostic')
        require(not (out/'invalid-output.mlir').exists() or (out/'invalid-output.mlir').stat().st_size == 0, 'Failed IR left a nonempty generated artifact')
        run([heco, '--cpg-nonexistent-mode', 'input.mlir'], 'invalid-option', expected_failure=True)
        artifacts = []
        for name in ['input.mlir','optimized.mlir','bfv.mlir','emitc.mlir','generated.cpp','driver.cpp','encrypted-driver']:
            path = out/name
            artifacts.append({'path':name,'sha256':digest(path),'bytes':path.stat().st_size})
        result = {'status':'passed','resource':'research.heco','profile':'HECO transpiler via paired LLVM/MLIR 17.0.6 SDK; manual SEAL C++ execution','host_cxx_version':compiler_version,'heco_llvm_version':heco_version, 'cases':checked,'checked_lane_values':36,'checked_padding_lanes_per_output':4092, 'commands':commands,'artifacts':artifacts,'offline_policy':policy, 'negative_tests':{'invalid_ir_rejected':True,'invalid_option_rejected':True},'qualified':{'material':True,'functional':True,'heco_source_build':True,'seal_source_build':True,'llvm_source_build':False,'interactive_mode':False,'compiler_mode':False,'cryptographic_security_proof':False},'pipeline_note':'BFV diagnostic snapshot is not reparsed: the unchanged upstream custom printer omits quotes around its string parameter; FHE-to-BFV-to-EmitC lowering runs in one in-memory pipeline.', 'runtime_parameter_note':'BFV parameters are explicitly set by the manual driver; the HECO source contains incomplete parameter metadata and this test does not claim automatic cryptographic parameter selection.'}
        result_path=out/'result.json'
        result_path.write_text(json.dumps(result,indent=2)+'\n')
        temporary=base/('last-result-'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps({'status':'passed','result_path':str(result_path),'result_sha256':digest(result_path)},indent=2)+'\n')
        temporary.replace(pointer)
        print('PASS: HECO transpiler -> SEAL, 3 operations x 3 synthetic cases x 4 slots = 36 exact values')
        print('RESULT: '+str(result_path))
    except BaseException:
        (out/'failure.txt').write_text(traceback.format_exc())
        (out/'commands-until-failure.json').write_text(json.dumps(commands,indent=2)+'\n')
        raise

if __name__=='__main__':
    main()
