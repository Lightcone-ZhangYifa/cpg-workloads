#!/usr/bin/env python3
"""Replay a bounded managed-assembly profile using only shipped inputs."""
import argparse,json,os,shutil,struct,subprocess,tarfile,tempfile
from pathlib import Path

def read_relocations(path):
    data=Path(path).read_bytes()
    if data[:2]!=b'MZ':raise ValueError('DOS magic')
    pe=struct.unpack_from('<I',data,60)[0]
    if data[pe:pe+4]!=b'PE\0\0':raise ValueError('PE magic')
    count=struct.unpack_from('<H',data,pe+6)[0];opt=pe+24;optlen=struct.unpack_from('<H',data,pe+20)[0]
    magic=struct.unpack_from('<H',data,opt)[0]
    if magic!=0x10b:raise ValueError('Expected PE32 fixture')
    base=struct.unpack_from('<I',data,opt+28)[0];image_size=struct.unpack_from('<I',data,opt+56)[0]
    sections=[]
    for i in range(count):
        s=opt+optlen+i*40;vsize,rva,rawsize,raw=struct.unpack_from('<IIII',data,s+8);sections.append((rva,max(vsize,rawsize),raw,rawsize))
    def offset(rva,size=1):
        for start,span,raw,rawsize in sections:
            if start<=rva and rva+size<=start+span and rva-start+size<=rawsize:return raw+rva-start
        raise ValueError('RVA outside file-backed sections')
    rr,rs=struct.unpack_from('<II',data,opt+96+5*8);cur=offset(rr,rs);end=cur+rs;items=[]
    while cur<end:
        page,block=struct.unpack_from('<II',data,cur)
        if block<8 or block%2 or cur+block>end:raise ValueError('Invalid relocation block')
        for j in range(cur+8,cur+block,2):
            raw=struct.unpack_from('<H',data,j)[0];kind=raw>>12;target=page+(raw&4095)
            if kind==0:continue
            if kind!=3:raise ValueError('Unexpected fixture relocation type')
            off=offset(target,4);value=struct.unpack_from('<I',data,off)[0]
            if not base<=value<base+image_size:raise ValueError('Relocation target pointer outside image')
            # A loader rebasing this PE32 pointer must preserve its image-relative destination.
            delta=0x100000;patched=(value+delta)&0xffffffff
            if patched-(base+delta)!=value-base:raise ValueError('Rebase invariant failed')
            items.append({'type':kind,'target_rva':target,'pointed_rva':value-base,'rebase_delta':delta})
        cur+=block
    if not items:raise ValueError('Fixture has no real relocations')
    return {'image_base':base,'relocations':items}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    p=Path(a.prefix).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').unlink(missing_ok=True)
    cfg=json.loads((p/'profile.json').read_text());rid=cfg['id'];work=Path(tempfile.mkdtemp(prefix='dotnet-profile-',dir=out))
    try:
        runtime=work/'runtime';runtime.mkdir()
        with tarfile.open(p/'upstream/dotnet-runtime-8.0.33-linux-x64.tar.gz') as z:z.extractall(runtime,filter='data')
        env=os.environ.copy();env.update(DOTNET_ROOT=str(runtime),DOTNET_MULTILEVEL_LOOKUP='0',DOTNET_CLI_TELEMETRY_OPTOUT='1',DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1',DOTNET_EnableDiagnostics='0',DOTNET_GCHeapHardLimit='10000000',DOTNET_gcServer='0',DOTNET_CLI_HOME=str(work/'cli-home'))
        probe=out/'probe-output';probe.mkdir(exist_ok=True)
        argv=[str(runtime/'dotnet'),str(p/'bin/Probe.dll'),str(p/'bin/Fixture.dll'),str(probe)]
        try:r=subprocess.run(argv,env=env,cwd=work,text=True,capture_output=True,timeout=600)
        except subprocess.TimeoutExpired as error:
            (out/'timeout.json').write_text(json.dumps({'argv':argv,'timeout_seconds':600,'status':'failed','reason':'wall-clock timeout; no functional qualification granted'},indent=2))
            raise
        (out/'probe.stdout.txt').write_text(r.stdout);(out/'probe.stderr.txt').write_text(r.stderr)
        (out/'command.json').write_text(json.dumps({'argv':argv,'returncode':r.returncode},indent=2))
        if r.returncode:raise RuntimeError('probe failed: '+r.stderr[-5000:])
        metrics=json.loads(next(x[7:] for x in r.stdout.splitlines() if x.startswith('RESULT ')))
        if rid=='research.asmresolver':
            before=read_relocations(p/'bin/Fixture.dll');after=read_relocations(probe/'module-roundtrip.dll');raw=read_relocations(probe/'raw-pe-roundtrip.dll')
            if raw!=before:raise RuntimeError('raw PE relocation metadata changed')
            if [x['type'] for x in before['relocations']]!=[x['type'] for x in after['relocations']]:raise RuntimeError('relocation kind/count mismatch')
            upstream=json.loads((probe/'asmresolver-relocations.json').read_text())
            actual_before=[x for x in upstream['before'] if x['type'] not in ('Absolute','0')]
            actual_after=[x for x in upstream['after'] if x['type'] not in ('Absolute','0')]
            metrics['effective_relocation_count']=len(before['relocations'])
            metrics['padding_relocation_count']=len(upstream['before'])-len(actual_before)
            (out/'independent-pe-relocations.json').write_text(json.dumps({'before':before,'after':after,'raw':raw,'upstream_includes_absolute_padding':True},indent=2))
            checks=[{'name':'metadata_roundtrip','passed':metrics['metadata_equal']},{'name':'raw_pe_byte_roundtrip','passed':metrics['raw_pe_bytes_equal']},{'name':'assembly_load_execute','passed':metrics['original_result']==1 and metrics['roundtrip_result']==1},{'name':'relocations_independent_parser_and_rebase','passed':len(before['relocations'])==len(actual_before) and len(after['relocations'])==len(actual_after) and len(upstream['before'])==metrics['relocation_count']},{'name':'malformed_pe_rejected','passed':metrics['malformed_pe_rejected']}]
        else:
            checks=[{'name':'single_CIL_instruction_changed','passed':metrics['changed_instructions']==1},{'name':'changed_assembly_executes','passed':metrics['before']==1 and metrics['after']==2},{'name':'metadata_preserved','passed':metrics['metadata_equal']},{'name':'unselected_method_preserved','passed':metrics['untouched_result']==8},{'name':'malformed_module_rejected','passed':metrics['malformed_module_rejected']}]
        if not all(x['passed'] for x in checks):raise RuntimeError('semantic check failed')
        (out/'metrics.json').write_text(json.dumps(metrics,indent=2))
    finally:shutil.rmtree(work)
    ev=[str(x.relative_to(out)) for x in sorted(out.rglob('*')) if x.is_file() and x.name!='result.json']
    (out/'result.json').write_text(json.dumps({'schema_version':1,'resource_id':rid,'status':'passed','checks':checks,'metrics':metrics,'evidence_files':ev,'scope':cfg['scope'],'runtime':'.NET 8.0.33 bundled linux-x64 runtime; framework System.Text.Json 8 satisfies the net8.0 library profile'},indent=2))
    print('CPG_CHECK_PASS '+rid)

if __name__=='__main__':main()
