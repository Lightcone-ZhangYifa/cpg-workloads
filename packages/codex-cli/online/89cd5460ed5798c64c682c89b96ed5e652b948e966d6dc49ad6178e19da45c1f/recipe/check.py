#!/usr/bin/env python3
"""Check the complete original Codex bundle and bounded offline CLI functions.

Never invokes login, update, cloud, exec, review, an agent session, a daemon,
or the app-server transport. Only completion/schema generation, feature-list
parsing, argument rejection and bundled ripgrep are exercised.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def snapshot(prefix):
    rows=[]
    for path in sorted(prefix.rglob('*')):
        name=path.relative_to(prefix).as_posix()
        if name=='.cpg-prefix.json':continue
        info=path.lstat();row={'path':name,'mode':stat.S_IMODE(info.st_mode)}
        if stat.S_ISDIR(info.st_mode):row['kind']='directory'
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink!=1:raise ValueError('Bundle file must have independent ownership: '+name)
            row.update(kind='file',sha256=sha(path),bytes=info.st_size)
        else:raise ValueError('Bundle must contain ordinary files and directories only: '+name)
        rows.append(row)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output-contract',type=Path,required=True)
    parser.add_argument('--integrity-only',action='store_true')
    args=parser.parse_args()
    expected=json.loads(args.manifest.read_text())
    actual=snapshot(args.prefix)
    if actual!=expected['files']:raise ValueError('Complete original bundle inventory mismatch')
    report={'status':'passed','resource_id':'codex-cli','ordinary_file_count':sum(x['kind']=='file' for x in actual),
        'scope':'complete upstream native bundle integrity only' if args.integrity_only else 'local CLI functionality of the complete upstream precompiled bundle only',
        'cloud_account_qualified':False,'remote_agent_task_executed':False,'native_source_compiled':False,
        'voice_or_code_mode_companion_executed':False,'oci_qualified':False,'hardware_qualified':False}
    if args.integrity_only:
        print(json.dumps(report,sort_keys=True));return
    root=args.prefix/'vendor/x86_64-unknown-linux-musl'
    binary=root/'bin/codex';rg=root/'codex-path/rg'
    contract=json.loads(args.output_contract.read_text())
    commands=[]
    env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8'}
    with tempfile.TemporaryDirectory(prefix='cpg-codex-local-check-') as temp:
        work=Path(temp)
        def run(argv,expected_returncode=0):
            result=subprocess.run([str(x) for x in argv],cwd=work,env=env,capture_output=True,text=True,timeout=60)
            commands.append({'argv':[str(x) for x in argv],'returncode':result.returncode,
                'stdout_sha256':hashlib.sha256(result.stdout.encode()).hexdigest(),'stdout_bytes':len(result.stdout.encode()),
                'stderr':result.stderr,'stdout_excerpt':result.stdout[:300]})
            if result.returncode!=expected_returncode:raise ValueError('Local CLI failed: '+repr(commands[-1]))
            return result
        version=run([binary,'--version']).stdout.strip()
        if version!='codex-cli 0.163.0':raise ValueError('Original version changed: '+version)
        completion=run([binary,'completion','bash']).stdout
        if hashlib.sha256(completion.encode()).hexdigest()!=contract['bash_completion']['sha256'] or len(completion.encode())!=contract['bash_completion']['bytes']:
            raise ValueError('Generated completion differs from fixed original CLI output')
        script=work/'codex-completion.bash';script.write_text(completion)
        run(['/bin/bash','-n',script])
        features=run([binary,'features','list']).stdout
        parsed=[]
        for line in features.splitlines():
            match=re.fullmatch(r'(\S+)\s+(stable|experimental|under development|removed|deprecated)\s+(true|false)',line.strip())
            if not match:raise ValueError('Feature table cannot be parsed')
            parsed.append({'name':match[1],'stage':match[2],'enabled':match[3]=='true'})
        if [x['name'] for x in parsed]!=contract['feature_names'] or len({x['name'] for x in parsed})!=len(parsed):
            raise ValueError('Original feature inventory changed')
        output=work/'protocol-json-schema'
        run([binary,'app-server','generate-json-schema','--out',output])
        schemas=[]
        for path in sorted(output.rglob('*')):
            if path.is_symlink():raise ValueError('Generated schema unexpectedly linked')
            if path.is_dir():continue
            if path.suffix!='.json':raise ValueError('Unexpected generated protocol member')
            value=json.loads(path.read_text())
            if not isinstance(value,dict):raise ValueError('Generated JSON Schema must be an object')
            schemas.append({'path':path.relative_to(output).as_posix(),'sha256':sha(path),'bytes':path.stat().st_size})
        if schemas!=contract['protocol_schema_files']:raise ValueError('Generated fixed protocol schema inventory changed')
        bad=run([binary,'completion','not-a-shell'],expected_returncode=2)
        if "invalid value 'not-a-shell'" not in bad.stderr:raise ValueError('Bad argument failed for unrelated reason')
        fixture=work/'fixture';fixture.mkdir();(fixture/'input.txt').write_text('alpha\nCPG_FIXED_NEEDLE\nbeta CPG_FIXED_NEEDLE\nomega\n')
        matched=run([rg,'--json','--fixed-strings','CPG_FIXED_NEEDLE',fixture/'input.txt'])
        events=[json.loads(line) for line in matched.stdout.splitlines()]
        matches=[row['data'] for row in events if row['type']=='match']
        if [row['line_number'] for row in matches]!=[2,3] or [row['lines']['text'] for row in matches]!=['CPG_FIXED_NEEDLE\n','beta CPG_FIXED_NEEDLE\n']:
            raise ValueError('Bundled ripgrep actual matches incorrect')
        report.update(actual_commands=commands,actual_command_count=len(commands),version=version,
            feature_count=len(parsed),feature_rows=parsed,protocol_schema_files=schemas,
            protocol_schema_count=len(schemas),protocol_schema_bytes=sum(r['bytes'] for r in schemas),
            completion_generated_and_bash_syntax_valid=True,protocol_schemas_generated_and_all_json_parsed=True,
            invalid_argument_rejected=True,bundled_ripgrep_actual_match_lines=[2,3],
            credential_environment_variables_supplied=False,config_write_commands_invoked=False,
            generated_outputs_are_temporary_and_reproducible=True)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':main()
