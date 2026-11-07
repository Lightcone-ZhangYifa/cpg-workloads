#!/usr/bin/env python3
"""Bounded compiler/grammar acceptance, with actual positive and negative cases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(argv, work, expected=0):
    result = subprocess.run(list(map(str, argv)), cwd=work, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    record = {'argv': list(map(str, argv)), 'returncode': result.returncode,
              'stdout': result.stdout, 'stderr': result.stderr}
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if expected == 'failure':
        require(result.returncode != 0, 'negative case unexpectedly succeeded')
    else:
        require(result.returncode == expected, 'command failed: '+str(argv))
    return result


def spirv_validate(file, work):
    require(file.stat().st_size > 20 and file.stat().st_size % 4 == 0, 'SPIR-V word size')
    require(struct.unpack('<I', file.read_bytes()[:4])[0] == 0x07230203, 'SPIR-V magic')
    val = os.environ.get('CPG_SPIRV_VAL') or shutil.which('spirv-val')
    dis = os.environ.get('CPG_SPIRV_DIS') or shutil.which('spirv-dis')
    require(val and dis, 'SPIRV-Tools validator and disassembler are required verification inputs')
    execute([val, '--target-env', 'vulkan1.1', file], work)
    return execute([dis, file], work).stdout


def shaders(prefix, work, name):
    vertex = work/'minimal.vert'
    vertex.write_text('#version 450\nlayout(location=0) in vec4 pos;\nvoid main(){gl_Position=pos*2.0;}\n')
    compute = work/'minimal.comp'
    compute.write_text('#version 450\nlayout(local_size_x=4,local_size_y=2) in;\n'
                       'layout(set=0,binding=0,std430) buffer B { uint x[]; } b;\n'
                       'void main(){uint i=gl_GlobalInvocationID.x;b.x[i]=i+7u;}\n')
    bad = work/'invalid.vert'
    bad.write_text('#version 450\nvoid main(){gl_Position=bad_identifier;}\n')
    exe = prefix/'bin'/('glslang' if name == 'glslang' else 'glslc')
    execute([exe, '--version'], work)
    outputs = []
    for src in [vertex, compute]:
        out = work/(src.name+'.spv')
        command = ([exe, '-V', '--target-env', 'vulkan1.1', src, '-o', out]
                   if name == 'glslang' else [exe, '--target-env=vulkan1.1', src, '-o', out])
        execute(command, work)
        assembly = spirv_validate(out, work)
        require('OpEntryPoint' in assembly and 'OpFunction' in assembly, 'compiled SPIR-V instructions absent')
        if src == compute:
            require('LocalSize 4 2 1' in assembly and 'OpStore' in assembly, 'compute workgroup/store semantics')
        else:
            require('OpVectorTimesScalar' in assembly and 'float_2' in assembly, 'vertex multiply constant absent')
        outputs.append({'file': src.name, 'sha256': digest(out), 'bytes': out.stat().st_size})
    badout = work/'bad.spv'
    cmd = ([exe, '-V', bad, '-o', badout] if name == 'glslang' else [exe, bad, '-o', badout])
    negative = execute(cmd, work, expected='failure')
    require('bad_identifier' in negative.stdout+negative.stderr, 'negative diagnostic omitted offending token')
    require(not badout.exists(), 'invalid shader generated an output')
    if name == 'shaderc':
        cfile = Path(__file__).with_name('shaderc_api.c')
        obj = work/'api.o'
        execute(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-DSHADERC_SHAREDLIB',
                 '-I'+str(prefix/'include'), '-c', cfile, '-o', obj], work)
        products = []
        for kind in ['shared', 'combined']:
            consumer = work/('api-'+kind)
            cmd = ['c++', obj, '-L'+str(prefix/'lib'), '-lshaderc_'+kind, '-pthread', '-o', consumer]
            if kind == 'shared':
                cmd += ['-Wl,-rpath,'+str(prefix/'lib')]
            execute(cmd, work)
            out = work/('include-'+kind+'.spv')
            run = execute([consumer, out], work)
            require('SHADERC_C_API_OK' in run.stdout, 'C API completion marker absent')
            assembly = spirv_validate(out, work)
            require('float_2' in assembly, 'include-defined value absent from shader')
            products.append(digest(out))
        require(products[0] == products[1], 'static and shared C API SPIR-V differ')
    return {'name': name, 'status': 'passed', 'outputs': outputs,
            'scope': 'CPU compilation and SPIRV-Tools validation; no GPU execution'}


def headers(prefix, work):
    source = prefix/'share/spirv-headers'
    parsed = []
    for f in sorted((source/'include/spirv').rglob('*.grammar.json')):
        data = json.loads(f.read_text())
        require(isinstance(data.get('instructions'), list), 'grammar instructions are absent')
        names = [x['opname'] for x in data['instructions']]
        require(len(names) == len(set(names)), 'duplicate grammar instruction names')
        require(all(isinstance(x['opcode'], int) for x in data['instructions']), 'noninteger opcode')
        parsed.append({'path': str(f.relative_to(source)), 'instructions': len(names), 'sha256': digest(f)})
    require(len(parsed) >= 20, 'incomplete grammar collection')
    registry = ET.parse(source/'include/spirv/spir-v.xml')
    require(registry.getroot().tag == 'registry', 'registry XML root')
    core = source/'include/spirv/unified1/spirv.core.grammar.json'
    names = {x['opname'] for x in json.loads(core.read_text())['instructions']}
    require({'OpFunction', 'OpReturn', 'OpTypeInt', 'OpEntryPoint'} <= names, 'core opcode set')
    generated = work/'generated'
    generated.mkdir()
    execute([prefix/'bin/buildSpvHeaders', '-H', core], generated)
    comparisons = []
    for f in sorted(generated.iterdir()):
        reference = core.parent/f.name
        require(reference.is_file(), 'generated file lacks committed reference: '+f.name)
        require(f.read_bytes().replace(b'\r\n', b'\n') == reference.read_bytes().replace(b'\r\n', b'\n'),
                'regenerated core header differs: '+f.name)
        comparisons.append({'file': f.name, 'sha256': digest(f), 'reference_sha256': digest(reference)})
    require(len(comparisons) >= 8, 'header generator omitted languages')
    ext = work/'extinst'
    ext.mkdir()
    for stem, grammar in [('NonSemanticDebugPrintf', 'extinst.nonsemantic.debugprintf.grammar.json'),
                          ('OpenCLDebugInfo100', 'extinst.opencl.debuginfo.100.grammar.json')]:
        execute(['python3', source/'tools/buildHeaders/bin/generate_language_headers.py',
                 '--extinst-name='+stem, '--extinst-grammar='+str(core.parent/grammar),
                 '--extinst-output-base='+str(ext/stem)], ext)
        f = ext/(stem+'.h')
        require(f.read_bytes().replace(b'\r\n', b'\n') == (core.parent/f.name).read_bytes().replace(b'\r\n', b'\n'),
                'extended instruction regenerated header differs: '+stem)
    c = work/'consumer.c'
    c.write_text('#include <spirv/unified1/spirv.h>\n'
                 '_Static_assert(SpvOpReturn == 253, "return opcode");\n'
                 'int main(void){return SpvMagicNumber == 0x07230203 && SpvOpTypeInt == 21 ? 0 : 1;}\n')
    execute(['cc', '-std=c11', '-Werror', '-I'+str(prefix/'include'), c, '-o', work/'consumer'], work)
    execute([work/'consumer'], work)
    return {'name': 'spirv-headers', 'status': 'passed', 'grammars': parsed, 'regenerated': comparisons,
            'extended_headers_compared': 2, 'scope': 'grammar parsing and upstream generator reproducibility; not a validator'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('name', choices=['glslang', 'shaderc', 'spirv-headers'])
    p.add_argument('--prefix', required=True, type=Path)
    p.add_argument('--work', required=True, type=Path)
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=a.name+'-', dir=a.work) as temp:
        work = Path(temp).resolve()
        summary = headers(a.prefix.resolve(), work) if a.name == 'spirv-headers' else shaders(a.prefix.resolve(), work, a.name)
        (a.work/(a.name+'-summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
