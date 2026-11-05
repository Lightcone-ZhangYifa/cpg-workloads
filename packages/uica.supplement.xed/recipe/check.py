#!/usr/bin/env python3
"""Exercise the actually installed XED CLI, C library and generated ISA XML."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    args.build.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='xed-functional-', dir=args.build))
    share = prefix / 'share/uica.supplement.xed'
    profile = json.loads((prefix / 'share/compiler-playground/uica.supplement.xed/profile.json').read_text())
    records = []
    env = dict(os.environ, PATH='/usr/bin:/bin', PYTHONDONTWRITEBYTECODE='1', LC_ALL='C.UTF-8')
    for variable in ('PYTHONHOME', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD'):
        env.pop(variable, None)

    def run(label, argv, *, expected=0, timeout=120):
        argv = list(map(str, argv))
        completed = subprocess.run(argv, cwd=output, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        (output / (label + '.stdout')).write_bytes(completed.stdout)
        (output / (label + '.stderr')).write_bytes(completed.stderr)
        records.append({'label': label, 'argv': argv, 'cwd': str(output), 'returncode': completed.returncode,
                        'expected': expected, 'stdout': label + '.stdout', 'stderr': label + '.stderr'})
        (output / 'commands.json').write_text(json.dumps(records, indent=2, sort_keys=True) + '\n')
        need(completed.returncode != 0 if expected == 'nonzero' else completed.returncode == expected, 'Unexpected result: ' + label)
        return completed.stdout.decode(errors='replace'), completed.stderr.decode(errors='replace')

    need((prefix / 'bin/xed').read_bytes()[:4] == b'\x7fELF', 'Installed decoder is not the built native executable')
    decoded, _ = run('decode-mov', [prefix / 'bin/xed', '-64', '-d', '4889d8'])
    need('MOV' in decoded.upper() and 'RAX' in decoded.upper() and 'RBX' in decoded.upper(), 'CLI decoded different operands')
    encoded, _ = run('encode-add', [prefix / 'bin/xed-ex3', '-64', 'ADD/64', 'RAX', 'RBX'])
    need('4801D8' in encoded.upper().replace(' ', ''), 'CLI encoder did not emit ADD RAX,RBX')
    run('invalid-cli-option', [prefix / 'bin/xed', '-cpg-invalid-option'], expected='nonzero')
    run('invalid-encoder-request', [prefix / 'bin/xed-ex3', 'CPG_INVALID_INSTRUCTION'], expected='nonzero')
    # Fresh client compile is linked only to this prefix's installed XED archive.
    probe = output / 'api-probe'
    run('compile-installed-c-api', ['/usr/bin/gcc', '-std=c11', '-O2', '-I' + str(prefix / 'include'),
        share / 'api_probe.c', prefix / 'lib/libxed.a', '-o', probe])
    result, _ = run('installed-c-api', [probe])
    need('truncated-input rejection passed' in result, 'Installed API probe did not complete its negative control')
    xml = share / 'instructions.xml'
    need(xml.stat().st_size == profile['generated_isa_xml']['bytes'] and sha(xml) == profile['generated_isa_xml']['sha256'], 'Installed generated XML identity differs')
    tree = ET.parse(xml)
    instructions = list(tree.getroot().iter('instruction'))
    need(len(instructions) == profile['generated_isa_xml']['instructions'], 'Installed XML lost instruction records')
    shutil.copyfile(xml, output / 'instructions.xml')
    assembly, _ = run('upstream-xml-to-assembler', ['/usr/bin/python3', '-B', share / 'source/xmlToAssembler.py'])
    lines = assembly.splitlines()
    need(lines and lines[0] == '.intel_syntax noprefix' and len(lines) > 1000, 'Upstream XML conversion did not execute')
    receipt = {'status': 'passed', 'commands_executed': len(records), 'negative_cli_commands': 2,
        'native_api_semantic_probes': ['MOV decode and operands', 'encode/decode identity', 'truncated-byte rejection'],
        'xml_instruction_records': len(instructions), 'assembler_lines_emitted': len(lines) - 1,
        'all_assembler_lines_compiled': False, 'prefix': str(prefix), 'execution_directory': str(output),
        'host_compiler': {'path': '/usr/bin/gcc', 'resolved_path': str(Path('/usr/bin/gcc').resolve()), 'sha256': sha(Path('/usr/bin/gcc').resolve())},
        'scope': 'Native software decoding/encoding; decoded CPU instructions were not executed on physical target hardware'}
    (output / 'checks.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
