#!/usr/bin/env python3
"""Bounded native LLVM/Clang structured-fuzzer checks with exact bindings."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from capability_check import Audit, sha, verify_payload

REVISION = '7a941dfb2877a0b8cf30323fefa85ad019e0b0f5'
TRIPLE = 'x86_64-unknown-linux-gnu'
PROTO_TEXTS = {
    'assignment': 'statements { statements { assignment { lvalue { varref { varnum: 0 } } rvalue { cons { val: 7 } } } } }\n',
    'branch': 'statements { statements { ifelse { cond { varref { varnum: 0 } } if_body { statements { assignment { lvalue { varref { varnum: 1 } } rvalue { cons { val: 9 } } } } } else_body {} } } }\n',
    'loop': 'statements { statements { while_loop { cond { cons { val: 0 } } body { statements { assignment { lvalue { varref { varnum: 2 } } rvalue { cons { val: 3 } } } } } } } }\n',
}
IR_TEXTS = {
    'arithmetic': 'define i32 @f(i32 %x) {\nentry:\n  %a = add i32 %x, 1\n  ret i32 %a\n}\n',
    'select': 'define i32 @f(i32 %x) {\nentry:\n  %c = icmp slt i32 %x, 5\n  %s = select i1 %c, i32 %x, i32 5\n  ret i32 %s\n}\n',
    'loop': 'define i32 @f(i32 %x) {\nentry:\n  br label %loop\nloop:\n  %i = phi i32 [0, %entry], [%n, %loop]\n  %n = add i32 %i, 1\n  %c = icmp ult i32 %n, 4\n  br i1 %c, label %loop, label %exit\nexit:\n  %r = add i32 %x, %n\n  ret i32 %r\n}\n',
}


def make_seeds(a, lpm):
    lpm=Path(lpm).resolve(strict=True)
    schema = a.root/'share/llvm-source/clang/tools/clang-fuzzer/cxx_proto.proto'
    seeds = a.output/'seeds'
    seeds.mkdir(exist_ok=True)
    result = {'clang-proto-fuzzer':[], 'llvm-opt-fuzzer':[], 'llvm-isel-fuzzer':[]}
    for name, text in PROTO_TEXTS.items():
        (seeds/(name+'.textproto')).write_text(text)
        encoded = a.run('encode-proto-'+name, [Path(lpm)/'protobuf/bin/protoc',
            '-I'+str(schema.parent), '--encode=clang_fuzzer.Function', schema], stdin=text.encode())
        target = seeds/(name+'.pb')
        target.write_bytes(encoded.stdout)
        if not encoded.stdout:
            raise AssertionError('Empty encoded seed: '+name)
        result['clang-proto-fuzzer'].append(target)
    for name, text in IR_TEXTS.items():
        source = seeds/(name+'.ll')
        source.write_text('; Local synthetic seed, Apache-2.0 WITH LLVM-exception\n'
                          +'target triple = "'+TRIPLE+'"\n'+text)
        target = seeds/(name+'.bc')
        a.run('assemble-ir-'+name, [a.tool('llvm-as'), source, '-o', target])
        result['llvm-opt-fuzzer'].append(target)
        result['llvm-isel-fuzzer'].append(target)
    return result


def campaign(a, kind, seeds, *, seed, runs=32, print_pcs=False, label=None):
    if type(runs) is not int or not 1 <= runs <= 256:
        raise ValueError('Campaign must have an explicit bound of 1..256 runs')
    label = label or kind+'-'+str(seed)
    root = a.output/label
    corpus = root/'corpus'
    corpus.mkdir(parents=True)
    for source in seeds:
        shutil.copy2(source, corpus/source.name)
    graph = root/'mutation-graph.dot'
    profile = ['-O1'] if kind == 'clang-proto-fuzzer' else (
        ['-mtriple='+TRIPLE, '-passes=instcombine'] if kind == 'llvm-opt-fuzzer'
        else ['-mtriple='+TRIPLE, '-O0'])
    flags = ['-seed='+str(seed), '-runs='+str(runs), '-max_len='+str(1024 if kind == 'clang-proto-fuzzer' else 4096),
             '-timeout=10', '-rss_limit_mb=1024', '-reduce_inputs=0', '-reload=0',
             '-print_final_stats=1', '-mutation_graph_file='+str(graph)]
    if print_pcs:
        flags.append('-print_pcs=1')
    result = a.run(label, [a.tool(kind), corpus]+flags+['-ignore_remaining_args=1']+profile,
                   timeout=300, cwd=root,
                   env={'PATH':str(a.root/'bin')+os.pathsep+os.environ.get('PATH',''),
                        'ASAN_SYMBOLIZER_PATH':str(a.tool('llvm-symbolizer'))})
    output = (result.stdout+result.stderr).decode(errors='replace')
    if not re.search(r'Loaded \d+ modules.*inline 8-bit counters', output):
        raise AssertionError('Native libFuzzer coverage counters were not observed: '+kind)
    if 'Done '+str(runs)+' runs' not in output:
        raise AssertionError('Finite libFuzzer run bound was not observed: '+kind)
    if not graph.is_file():
        raise AssertionError('Stock libFuzzer mutation graph missing: '+kind)
    rows = [{'name':f.name, 'sha1':hashlib.sha1(f.read_bytes()).hexdigest(),
             'sha256':sha(f), 'bytes':f.stat().st_size} for f in sorted(corpus.iterdir()) if f.is_file()]
    return {'name':label, 'kind':kind, 'root':root, 'corpus':corpus, 'graph':graph,
            'files':rows, 'seed':seed, 'runs':runs, 'target':TRIPLE,
            'compiler_arguments':profile, 'binary_sha256':sha(a.tool(kind)),
            'instrumentation':'Clang Parse/Lex and fuzzer code; LLVM FuzzMutate/FuzzerCLI and fuzzer code; other LLVM/Clang libraries uninstrumented',
            'stdout':output}


def check(a, lpm, runs=32):
    lpm=Path(lpm).resolve(strict=True)
    seeds = make_seeds(a, lpm)
    reports=[]
    for index, kind in enumerate(seeds):
        reports.append(campaign(a, kind, seeds[kind], seed=320032+index, runs=runs))
    # A dedicated single-input trace proves the instrumented compiler frontend
    # is entered, in addition to binary/link-map provenance.
    trace=campaign(a, 'clang-proto-fuzzer', seeds['clang-proto-fuzzer'][:1],
                   seed=320099, runs=4, print_pcs=True, label='clang-frontend-coverage-trace')
    covered=[line for line in trace['stdout'].splitlines()
             if 'NEW_PC:' in line and re.search(r'clang::(?:Parser|Lexer)|clang::ParseAST',line)]
    if not covered:
        raise AssertionError('No actual instrumented Clang parser/lexer coverage was symbolized')
    (a.output/'frontend-covered-pcs.txt').write_text('\n'.join(covered)+'\n')
    schema=a.root/'share/llvm-source/clang/tools/clang-fuzzer/cxx_proto.proto'
    bad_proto=a.output/'invalid.pb'
    bad_proto.write_bytes(b'\xff\xff\xff\xff\xff')
    a.run('reject-malformed-protobuf', [Path(lpm)/'protobuf/bin/protoc', '-I'+str(schema.parent),
          '--decode=clang_fuzzer.Function', schema], stdin=bad_proto.read_bytes(), expected=1)
    conversion=a.run('converter-invalid-protobuf', [a.tool('clang-proto-to-cxx'),'invalid.pb'])
    if b'#error' not in conversion.stdout:
        raise AssertionError('Native converter did not signal malformed input')
    invalid_cxx=a.output/'invalid.cpp';invalid_cxx.write_bytes(conversion.stdout)
    a.run('reject-converted-error-source', [a.tool('clang'),'-std=c++17','-fsyntax-only',invalid_cxx],expected=1)
    bad_ir=a.output/'invalid.bc';bad_ir.write_bytes(b'not llvm bitcode\n')
    a.run('reject-malformed-ir-oracle', [a.tool('opt'),'-passes=verify','-disable-output',bad_ir],expected=1)
    accepted_exit=a.run('fuzzer-exit-zero-is-not-validity', [a.tool('llvm-opt-fuzzer'), bad_ir,
        '-runs=1','-ignore_remaining_args=1','-mtriple='+TRIPLE,'-passes=instcombine'])
    if b'input module is broken' not in accepted_exit.stderr:
        raise AssertionError('Expected upstream invalid-IR diagnostic was not observed')
    a.run('reject-unknown-pass-pipeline', [a.tool('llvm-opt-fuzzer'), '-runs=1',
        '-ignore_remaining_args=1','-mtriple='+TRIPLE,'-passes=cpg-no-such-pass'],expected=1)
    a.run('reject-missing-target', [a.tool('llvm-opt-fuzzer'), '-runs=1',
        '-ignore_remaining_args=1','-passes=instcombine'],expected=1)
    return {'schema_version':1,'status':'passed','capability':'structured-fuzzing',
            'native_targets':[r['kind'] for r in reports],
            'bounded_runs_per_target':runs,'retained_corpus_files':[len(r['files']) for r in reports],
            'frontend_covered_pcs':len(covered),'mutation_graphs_preserved':True,
            'upstream_exit_zero_invalid_input_detected_separately':True,
            'llvm_revision':REVISION,'whole_llvm_release_qualification':False,
            'whole_lpm_resource_qualification':False,'instrumented_optimizer_claim':False,
            'ASAN_UBSAN_claim':False,'semantic_equivalence_claim':False,'performance_claim':False,
            'network_used':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('toolchain','lock','lpm','lpm-lock'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--output');p.add_argument('--output-parent');p.add_argument('--runs',type=int,default=32)
    a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='cpg-structured-') as temporary:
        if a.output_parent:
            parent=Path(a.output_parent);parent.mkdir(parents=True,exist_ok=True)
            output=Path(tempfile.mkdtemp(prefix='structured-',dir=parent))
        else:output=Path(a.output or temporary)
        audit=Audit(a.toolchain,output)
        needed=['clang','opt','llvm-as','llvm-symbolizer','clang-proto-fuzzer',
                'clang-proto-to-cxx','llvm-opt-fuzzer','llvm-isel-fuzzer']
        audit.validate(a.lock,needed);verify_payload(a.lpm,a.lpm_lock)
        result=check(audit,a.lpm,a.runs)
        audit.validate(a.lock,needed);verify_payload(a.lpm,a.lpm_lock)
        (output/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
