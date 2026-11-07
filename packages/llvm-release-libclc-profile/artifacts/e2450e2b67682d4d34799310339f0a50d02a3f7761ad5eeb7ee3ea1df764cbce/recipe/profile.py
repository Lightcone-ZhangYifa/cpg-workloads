#!/usr/bin/env python3
"""Bounded llvm-release libclc capability. No network; no full LLVM claim."""
import argparse
import ctypes
import hashlib
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import random
import shutil
import subprocess
import tarfile
import time
import uuid

SOURCE_SHA256 = '819ecf7351f1a66f76b2d701d8942faaf5faeb324cb90c9d5b090de142434bb2'
SOURCE_SIZE = 179272572
RESOURCE = 'llvm-release-libclc-profile'
FILES = ['clc/lib/generic/integer/clc_add_sat.cl',
         'opencl/lib/generic/integer/add_sat.cl',
         'clc/lib/generic/integer/clc_sub_sat.cl',
         'opencl/lib/generic/integer/sub_sat.cl']
CONSUMER = '''__kernel void libclc_vector_probe(__global const int *a, __global const int *b, __global int *out) {
  int4 av=(int4)(a[0],a[1],a[2],a[3]);
  int4 bv=(int4)(b[0],b[1],b[2],b[3]);
  int4 sum=add_sat(av,bv), diff=sub_sat(av,bv);
  out[0]=sum.s0;out[1]=sum.s1;out[2]=sum.s2;out[3]=sum.s3;
  out[4]=diff.s0;out[5]=diff.s1;out[6]=diff.s2;out[7]=diff.s3;
}
__kernel void libclc_scalar_probe(__global int *s, __global uint *u,
                                 __global long *l, __global ulong *v) {
  s[2]=add_sat(s[0],s[1]);s[3]=sub_sat(s[0],s[1]);
  u[2]=add_sat(u[0],u[1]);u[3]=sub_sat(u[0],u[1]);
  l[2]=add_sat(l[0],l[1]);l[3]=sub_sat(l[0],l[1]);
  v[2]=add_sat(v[0],v[1]);v[3]=sub_sat(v[0],v[1]);
}
'''


def allowed_symbols(stem):
    function = '__'+stem if stem.startswith('clc_') else stem
    prefix = '_Z'+str(len(function))+function
    return [prefix+s for s in ['ii','jj','ll','mm','Dv4_iS_']]


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def run(argv, work, name, expected=0):
    work = Path(work)
    start = time.monotonic()
    try:
        process = subprocess.run([str(x) for x in argv], cwd=work, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
        record = {'argv': [str(x) for x in argv], 'cwd': str(work),
                  'returncode': process.returncode, 'stdout': process.stdout,
                  'stderr': process.stderr, 'elapsed_seconds': time.monotonic()-start}
    except subprocess.TimeoutExpired as exc:
        write(work/(name+'.json'), {'argv': [str(x) for x in argv],
              'timeout_seconds': 600, 'elapsed_seconds': time.monotonic()-start,
              'stdout': str(exc.stdout), 'stderr': str(exc.stderr)})
        raise
    write(work/(name+'.json'), record)
    if expected is not None:
        require(process.returncode == expected,
                f'{name}: returncode {process.returncode}; see {work/(name+".json")}')
    return record


def compiler_args(source, target):
    return ['-target', target, '-x', 'cl', '-cl-std=CL3.0', '-Xclang',
            '-finclude-default-header', '-I'+str(source/'clc/include'),
            '-I'+str(source/'opencl/include'),
            '-D__CLC_PRIVATE_ADDRSPACE_VAL=0', '-D__CLC_GENERIC_ADDRSPACE_VAL=4']


def extract(archive, destination):
    require(archive.stat().st_size == SOURCE_SIZE, 'LLVM archive size mismatch')
    require(sha(archive) == SOURCE_SHA256, 'LLVM archive sha256 mismatch')
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    with tarfile.open(archive, 'r|xz') as stream:
        for member in stream:
            parts = PurePosixPath(member.name).parts
            relative = parts[1:] if len(parts)>1 else ()
            wanted = relative and (relative[0]=='libclc' or
                relative in [('LICENSE.TXT',), ('llvm','LICENSE.TXT')])
            if wanted and member.isfile():
                require('..' not in relative and not member.name.startswith('/'),
                        'unsafe selected archive member')
                path = destination.joinpath(*relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as reader, path.open('wb') as writer:
                    shutil.copyfileobj(reader, writer)
                path.chmod(0o644)
                records.append({'path': '/'.join(relative), 'bytes': member.size,
                                'sha256': sha(path)})
            stream.members.clear()  # bounded memory for the full monorepo archive
    require(any(r['path'].endswith('/clc_add_sat.cl') for r in records),
            'libclc source not found')
    write(destination/'source-members.json', records)
    return records


def build(args):
    install_prefix, tool = args.prefix.resolve(), args.tool_prefix.resolve()
    work = args.work.resolve()
    source_root = work.parent/(work.name+'-source')
    for left,right in [(install_prefix,work),(install_prefix,source_root),(work,source_root)]:
        require(left!=right and left not in right.parents and right not in left.parents,
                'source, build and installation paths must be disjoint')
    require(args.archive is not None,'build requires the exact pinned --archive')
    if install_prefix.exists():
        require(all(p.name=='.cpg-prefix.json' for p in install_prefix.iterdir()),
                'installation prefix contains existing non-owner data')
    work.mkdir(parents=True, exist_ok=False)
    prefix = work/'stage'
    share = prefix/'share'/RESOURCE
    share.mkdir(parents=True, exist_ok=False)
    records = extract(args.archive.resolve(), source_root)
    source = source_root/'libclc'
    (share/'consumer.cl').write_text(CONSUMER)
    bitcode = prefix/'lib'/RESOURCE
    bitcode.mkdir(parents=True, exist_ok=True)
    outputs = []
    native_objects = []
    version = run([tool/'bin/clang','--version'], work, 'compiler-version')['stdout']
    require('19.1.7' in version, 'qualified toolchain is the pinned OpenCilk LLVM 19.1.7')
    for index, name in enumerate(FILES):
        path = source/name
        stem = path.stem
        out = bitcode/(stem+'.bc')
        raw = work/(stem+'-all-overloads.bc')
        run([tool/'bin/clang',*compiler_args(source,'spir64-unknown-unknown'),
             '-I'+str(path.parent),'-c','-emit-llvm','-O1',path,'-o',raw],
             work, f'device-{index}')
        symbols=allowed_symbols(stem)
        run([tool/'bin/opt','-passes=internalize,globaldce',
             '-internalize-public-api-list='+','.join(symbols),raw,'-o',out],
             work,f'device-select-{index}')
        defined=run([tool/'bin/llvm-nm','--defined-only',out],work,f'device-symbols-{index}')['stdout']
        actual={line.split()[-1] for line in defined.splitlines() if line.strip()}
        require(actual==set(symbols),'selected device symbol set mismatch')
        outputs.append(out)
        obj = work/(stem+'.o')
        native_raw=work/(stem+'-native-all.bc')
        native_bc=work/(stem+'-native.bc')
        run([tool/'bin/clang',*compiler_args(source,'x86_64-unknown-linux-gnu'),
             '-I'+str(path.parent),'-fPIC','-c','-emit-llvm','-O1',path,'-o',native_raw],
             work, f'native-{index}')
        run([tool/'bin/opt','-passes=internalize,globaldce',
             '-internalize-public-api-list='+','.join(symbols),native_raw,'-o',native_bc],
             work,f'native-select-{index}')
        run([tool/'bin/clang','-fPIC','-c',native_bc,'-o',obj],work,f'native-object-{index}')
        native_objects.append(obj)
    consumer_bc = bitcode/'consumer.bc'
    run([tool/'bin/clang',*compiler_args(source,'spir64-unknown-unknown'),
         '-c','-emit-llvm','-O1',share/'consumer.cl','-o',consumer_bc],work,'device-consumer')
    linked = bitcode/'linked.bc'
    run([tool/'bin/llvm-link',*outputs,consumer_bc,'-o',linked],work,'device-link')
    run([tool/'bin/opt','-passes=verify','-disable-output',linked],work,'device-verify')
    undefined = run([tool/'bin/llvm-nm','--undefined-only',linked],work,'device-undefined')['stdout'].strip()
    require(not undefined, 'unresolved builtin(s) after device link: '+undefined)
    consumer_obj = work/'consumer.o'
    run([tool/'bin/clang',*compiler_args(source,'x86_64-unknown-linux-gnu'),
         '-fPIC','-c','-O1',share/'consumer.cl','-o',consumer_obj],work,'native-consumer')
    native = bitcode/'libclc_profile.so'
    run([tool/'bin/clang','-shared',*native_objects,consumer_obj,
         '-Wl,-z,defs','-Wl,-soname,libclc_profile.so','-o',native],work,'native-link')
    expected_symbols={s for f in FILES for s in allowed_symbols(Path(f).stem)} | {
        'libclc_scalar_probe','libclc_vector_probe'}
    exports=run([tool/'bin/llvm-nm','--dynamic','--defined-only',native],work,'native-exports')['stdout']
    actual_symbols={line.split()[-1] for line in exports.splitlines() if line.strip()}
    require(actual_symbols==expected_symbols,'native dynamic export set differs from exact allowlist')
    shutil.copy2(Path(__file__), share/'profile.py')
    shutil.copytree(source_root,share/'source')
    provenance = {'schema_version':1,'status':'built','parent_resource_id':'llvm-release',
        'technical_package_id':RESOURCE,'new_resource_family':False,
        'parent_source_sha256':SOURCE_SHA256,'parent_source_verified':True,'compiler_version':version,
        'source_build_install_separated':True,
        'selected_sources':FILES,'source_file_count':len(records),
        'qualified_scalar_types':['int','uint','long','ulong'],
        'qualified_vector_types':['int4'],
        'public_builtin_symbols': [s for f in FILES for s in allowed_symbols(Path(f).stem)],
        'device_target':'spir64-unknown-unknown','device_opencl_c':'CL3.0',
        'native_oracle_target':'x86_64-unknown-linux-gnu',
        'outputs':[{'path':str(p.relative_to(prefix)),'bytes':p.stat().st_size,'sha256':sha(p)}
                   for p in sorted(bitcode.iterdir()) if p.is_file()],
        'limits':['Two builtin families only: add_sat and sub_sat; int/uint/long/ulong scalars and int4.',
                  'LLVM19 narrow scalar promotion is incompatible with this LLVM23 source; 8/16-bit and all other vector overloads are removed from delivered bitcode/native objects.',
                  'No full libclc/LLVM build, SPIR-V translation, GPU execution or conformance claim.',
                  'Native oracle executes host-compiled OpenCL functions without an OpenCL runtime.']}
    write(share/'build-provenance.json',provenance)
    shutil.copytree(prefix,install_prefix,dirs_exist_ok=True)
    print(json.dumps({'status':'built','profile':RESOURCE,'source_file_count':len(records)}))


def check(args):
    prefix, tool = args.prefix.resolve(), args.tool_prefix.resolve()
    base = args.work.resolve()
    base.mkdir(parents=True, exist_ok=True)
    work = base/('check-'+uuid.uuid4().hex)
    work.mkdir()
    share = prefix/'share'/RESOURCE
    libs = prefix/'lib'/RESOURCE
    provenance = json.loads((share/'build-provenance.json').read_text())
    for record in provenance['outputs']:
        require(sha(prefix/record['path']) == record['sha256'], 'installed output hash mismatch')
    for record in json.loads((share/'source/source-members.json').read_text()):
        require(sha(share/'source'/record['path']) == record['sha256'], 'source member hash mismatch')
    source = share/'source/libclc'
    (work/'consumer.cl').write_text(CONSUMER)
    consumer = work/'consumer.bc'
    run([tool/'bin/clang',*compiler_args(source,'spir64-unknown-unknown'),
         '-c','-emit-llvm','-O1',work/'consumer.cl','-o',consumer],work,'fresh-consumer')
    bitcodes = [libs/(Path(f).stem+'.bc') for f in FILES]
    linked = work/'linked.bc'
    run([tool/'bin/llvm-link',*bitcodes,consumer,'-o',linked],work,'fresh-device-link')
    run([tool/'bin/opt','-passes=verify','-disable-output',linked],work,'fresh-device-verify')
    undefined = run([tool/'bin/llvm-nm','--undefined-only',linked],work,'fresh-undefined')['stdout'].strip()
    require(not undefined, 'fresh device consumer has unresolved calls')
    absent = work/'missing-implementation.bc'
    run([tool/'bin/llvm-link',bitcodes[0],bitcodes[1],bitcodes[3],consumer,'-o',absent],work,'negative-link')
    unresolved = run([tool/'bin/llvm-nm','--undefined-only',absent],work,'negative-undefined')['stdout']
    require('__clc_sub_sat' in unresolved, 'missing implementation negative did not expose unresolved calls')
    (work/'invalid.bc').write_bytes(b'CPG deliberately invalid LLVM bitcode\n')
    invalid = run([tool/'bin/llvm-link',work/'invalid.bc',consumer,'-o',work/'invalid-linked.bc'],
                  work,'negative-malformed',expected=None)
    require(invalid['returncode'] != 0, 'malformed bitcode incorrectly accepted')
    library = ctypes.CDLL(str(libs/'libclc_profile.so'))
    exports=run([tool/'bin/llvm-nm','--dynamic','--defined-only',libs/'libclc_profile.so'],work,'native-exports')['stdout']
    expected_symbols={s for f in FILES for s in allowed_symbols(Path(f).stem)} | {
        'libclc_scalar_probe','libclc_vector_probe'}
    require({line.split()[-1] for line in exports.splitlines() if line.strip()}==expected_symbols,
            'installed native dynamic export set differs from exact allowlist')
    for operation in ['add_sat','sub_sat']:
        for suffix in ['cc','hh','ss','tt','Dv2_iS_','Dv4_jS_']:
            try:
                getattr(library,'_Z7'+operation+suffix)
            except AttributeError:
                pass
            else:
                raise RuntimeError('unqualified overload was exported')
    scalar_types = [(32,True,'i',ctypes.c_int32),(32,False,'j',ctypes.c_uint32),
        (64,True,'l',ctypes.c_int64),(64,False,'m',ctypes.c_uint64)]
    rng = random.Random(20261101)
    scalar_results = []
    cases = 0
    for bits,signed,mangle,ctype in scalar_types:
        lower = -(1<<(bits-1)) if signed else 0
        upper = (1<<(bits-1))-1 if signed else (1<<bits)-1
        edges = sorted({lower,lower+1,0,1,upper-1,upper} | ({-1} if signed else set()))
        pairs = list(itertools.product(edges,repeat=2)) + [(rng.randint(lower,upper),rng.randint(lower,upper)) for _ in range(256)]
        for operation in ['add_sat','sub_sat']:
            function = getattr(library,'_Z7'+operation+mangle+mangle)
            function.argtypes = [ctype,ctype]
            function.restype = ctype
            for a,b in pairs:
                expected = min(upper,max(lower,a+b if operation=='add_sat' else a-b))
                observed = function(a,b)
                require(observed == expected,
                    f'{operation}/{bits}/{signed}: {a},{b}: {observed} != {expected}')
            cases += len(pairs)
            scalar_results.append({'operation':operation,'bits':bits,'signed':signed,
                                   'cases':len(pairs),'status':'passed'})
    vector = library.libclc_vector_probe
    pointer = ctypes.POINTER(ctypes.c_int32)
    vector.argtypes=[pointer,pointer,pointer]
    vector.restype=None
    lower,upper=-(1<<31),(1<<31)-1
    vectors=[([upper,lower,7,-3],[1,-1,-9,upper])]
    vectors += [([rng.randint(lower,upper) for _ in range(4)],
                 [rng.randint(lower,upper) for _ in range(4)]) for _ in range(64)]
    for av,bv in vectors:
        a=(ctypes.c_int32*4)(*av);b=(ctypes.c_int32*4)(*bv);out=(ctypes.c_int32*8)()
        vector(a,b,out)
        expected=[min(upper,max(lower,x+y)) for x,y in zip(av,bv)] + [min(upper,max(lower,x-y)) for x,y in zip(av,bv)]
        require(list(out)==expected,'native vector consumer result mismatch')
    result={'schema_version':1,'status':'passed','profile':RESOURCE,
        'parent_resource_id':'llvm-release','new_resource_family':False,
        'device_compile_link_verify':'passed','unresolved_device_symbols':[],
        'scalar_cases':cases,'scalar_results':scalar_results,
        'vector_inputs':len(vectors),'vector_lanes_checked':len(vectors)*8,
        'negative_controls':{'omitted_implementation_detected':True,'malformed_bitcode_rejected':True,
                             'unqualified_overloads_not_exported':True},
        'qualified_scalar_types':['int','uint','long','ulong'],'qualified_vector_types':['int4'],
        'source_sha256':SOURCE_SHA256,'linked_bitcode_sha256':sha(linked),
        'hardware_device_execution_qualified':False,
        'full_llvm_release_functional_qualification':False,
        'evidence_directory':str(work)}
    write(work/'result.json',result)
    print(json.dumps(result,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','check'])
    parser.add_argument('--prefix',type=Path,required=True)
    parser.add_argument('--tool-prefix',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    if args.action=='build':build(args)
    else:check(args)


if __name__=='__main__':
    main()
