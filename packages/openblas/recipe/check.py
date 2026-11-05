#!/usr/bin/env python3
"""Compile fresh consumers against exactly one installed OpenBLAS prefix."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

EXPECTED = {'status':'passed','numerical_cases':8,'invalid_parameters_rejected':5,
            'error_parameter_indices':[3,1,8,9,9],'version':'0.3.34'}


def clean_environment():
    env = dict(os.environ, LC_ALL='C', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    for name in ('LD_PRELOAD','LD_LIBRARY_PATH','LIBRARY_PATH','CPATH','C_INCLUDE_PATH',
                 'CPLUS_INCLUDE_PATH','CFLAGS','LDFLAGS','OPENBLAS_CORETYPE'):
        env.pop(name, None)
    return env


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def verify_linkage(text, prefix, shared):
    if 'not found' in text:
        raise RuntimeError('Unresolved runtime library')
    matches = [m.group(1) for line in text.splitlines()
               if (m:=re.match(r'^\s*libopenblas\S*\s+=>\s+(\S+)\s+\(',line))]
    if not shared:
        if matches:
            raise RuntimeError('Static consumer unexpectedly uses a dynamic OpenBLAS')
        return []
    actual = (prefix/'lib/libopenblas.so').resolve(strict=True)
    if len(matches)!=1 or Path(matches[0]).resolve(strict=True)!=actual or actual.parent!=(prefix/'lib').resolve(strict=True):
        raise RuntimeError('Consumer resolved a different OpenBLAS library')
    return [{'path':str(actual),'sha256':sha(actual),'bytes':actual.stat().st_size}]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix',type=Path,required=True)
    p.add_argument('--build',type=Path)
    p.add_argument('--case',choices=('shared','static','cli'),required=True)
    args=p.parse_args(); prefix=args.prefix.resolve(strict=True)
    report={'status':'running','resource':'openblas','case':args.case,'prefix':str(prefix),'commands':[]}
    env=clean_environment()
    try:
        profile=json.loads((prefix/'share/compiler-playground/openblas/profile.json').read_text())
        if profile['version']!='0.3.34' or profile['configuration']!=json.loads(Path(__file__).with_name('config.json').read_text())['configuration']:
            raise RuntimeError('Installed profile differs from this recipe')
        with tempfile.TemporaryDirectory(prefix='cpg-openblas-functional-') as tmp:
            tmp=Path(tmp)
            def run(argv,expected=0):
                argv=list(map(str,argv)); result=subprocess.run(argv,cwd=tmp,env=env,capture_output=True,text=True,timeout=120)
                report['commands'].append({'argv':argv,'cwd':str(tmp),'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
                if result.returncode!=expected:
                    raise RuntimeError('Unexpected command return code')
                return result
            if args.case=='cli':
                executable=prefix/'bin/openblas-cpg-probe'
            else:
                executable=tmp/'consumer'; suffix='so' if args.case=='shared' else 'a'
                run(['/usr/bin/gcc','-std=c11','-O2','-g0','-I'+str(prefix/'include'),
                     Path(__file__).with_name('consumer.c'),prefix/('lib/libopenblas.'+suffix),
                     '-Wl,-rpath,'+str(prefix/'lib'),'-lm','-pthread','-o',executable])
            report['info']=json.loads(run([executable,'--info']).stdout)
            result=json.loads(run([executable,'--self-test']).stdout)
            if result!=EXPECTED:
                raise RuntimeError('Incomplete numerical/error-handler checks')
            report['api']=result
            links=run(['/usr/bin/ldd',executable]).stdout
            report['selected_library']=verify_linkage(links,prefix,args.case!='static')
            if args.case=='cli':
                negative=run([executable,'--cpg-invalid-option'],expected=2)
                if 'usage:' not in negative.stderr:
                    raise RuntimeError('Invalid CLI option lacked usage diagnostic')
                report['cli_origin']='Project qualification probe built from the retained recipe; OpenBLAS is a library and does not supply this CLI upstream.'
                report['invalid_cli_options_rejected']=1
        report['status']='passed'
    except BaseException as error:
        report.update(status='failed',error=f'{type(error).__name__}: {error}')
        raise
    finally:
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
