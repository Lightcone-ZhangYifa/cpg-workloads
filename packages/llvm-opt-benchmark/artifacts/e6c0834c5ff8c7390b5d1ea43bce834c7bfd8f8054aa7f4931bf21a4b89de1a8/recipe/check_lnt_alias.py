#!/usr/bin/env python3
"""Guard the historical alias identity and execute its real bound LNT consumer."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def resolve(requested, alias_spec, target_spec, lock):
    if requested!='llvm-opt-benchmark':raise KeyError('This compatibility alias does not select the nightly IR corpus')
    if digest(alias_spec)!=lock['legacy_alias_definition_sha256']:raise ValueError('historical alias definition changed')
    if digest(target_spec)!=lock['legacy_lnt_definition_sha256']:raise ValueError('target legacy definition changed')
    if alias_spec['metadata']['catalog']['alias_of']!='llvm-lnt':raise ValueError('wrong alias target')
    if alias_spec['dependencies']['run']!=['llvm-lnt']:raise ValueError('wrong original dependency')
    return 'llvm-lnt'


def main(prefix,runtime,source,output):
    prefix,runtime,source=prefix.resolve(),runtime.resolve(),source.resolve()
    lock=json.loads((prefix/'alias.json').read_text())
    alias_file=prefix/'legacy-alias-package.json';target_file=prefix/'legacy-lnt-package.json'
    before=hashlib.sha256(alias_file.read_bytes()).hexdigest()
    alias=json.loads(alias_file.read_text());target=json.loads(target_file.read_text())
    resolved=resolve('llvm-opt-benchmark',alias,target,lock)
    for row in lock['runtime_files']:
        p=runtime/row['path']
        if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('bound LNT runtime changed: '+row['path'])
    output.mkdir(parents=True,exist_ok=True)
    run=Path(tempfile.mkdtemp(prefix='run-',dir=output))
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PIP_NO_INDEX='1')
    material_argv=['/usr/bin/python3',str(prefix/'material-check.py'),'--prefix',str(source),'--manifest',str(prefix/'material-manifest.json')]
    material=subprocess.run(material_argv,text=True,capture_output=True,env=env,timeout=180)
    (run/'material-check.log').write_text(material.stdout+material.stderr)
    if material.returncode:raise RuntimeError('bound original LNT source does not match its exact pin')
    negatives=[]
    try:resolve('llvm-opt-benchmark-nightly',alias,target,lock)
    except KeyError as e:negatives.append({'case':'nightly must not resolve to LNT','error':str(e)})
    else:raise AssertionError('nightly mis-resolved')
    forged=copy.deepcopy(target);forged['version']='forged-version'
    try:resolve('llvm-opt-benchmark',alias,forged,lock)
    except ValueError as e:negatives.append({'case':'changed historical target identity','error':str(e)})
    else:raise AssertionError('changed target accepted')
    argv=[str(runtime/'bin/python-lnt'),str(runtime/'scripts/check_lnt.py'),'--source',str(source),'--output',str(run/'actual-lnt-query')]
    result=subprocess.run(argv,text=True,capture_output=True,env=env,timeout=600)
    (run/'query.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('actual LNT consumer failed: '+str(run/'query.log'))
    queried=json.loads((run/'actual-lnt-query/result.json').read_text())
    assert queried['runs']==2 and queried['samples']==3
    assert hashlib.sha256(alias_file.read_bytes()).hexdigest()==before
    report={'status':'passed','requested_id':'llvm-opt-benchmark','resolved_id':resolved,
            'source_pin':queried['source_pin'],'legacy_alias_file_sha256_unchanged':before,
            'actual_lnt_query':queried,'negative_oracles':negatives,
            'binding':{'prefix':str(runtime),'source':str(source),'provider_profile':'cpg-worker031-runtime'},
            'scope':'explicit verified LNT consumer binding; no claim that legacy LNT APT installation succeeded; no nightly dataset substitution'}
    (run/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['prefix','runtime','source','output']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();main(a.prefix,a.runtime,a.source,a.output)
