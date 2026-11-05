#!/usr/bin/env python3
"""Compile and run new C++ consumers against one exact installed pugixml prefix."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

RESOURCE='intel-pcm.supplement.pugixml'
EXPECTED={'status':'passed','positive_cases':8,'malformed_xml_rejected':3,'invalid_xpath_rejected':2,'header_version':1150}

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix',type=Path,required=True);p.add_argument('--build',type=Path)
    p.add_argument('--case',choices=('shared','static','cli'),required=True);args=p.parse_args()
    prefix=args.prefix.resolve(strict=True);recipe=Path(__file__).resolve().parent
    report={'status':'running','resource':RESOURCE,'case':args.case,'prefix':str(prefix),'commands':[]}
    env=dict(os.environ,LC_ALL='C')
    for name in ('LD_PRELOAD','LD_LIBRARY_PATH','LIBRARY_PATH','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS'):
        env.pop(name,None)
    try:
        profile=json.loads((prefix/'share/compiler-playground'/RESOURCE/'profile.json').read_text())
        if profile['library_version']!='1.15' or profile['configuration']!=json.loads((recipe/'config.json').read_text())['configuration']:
            raise RuntimeError('Installed profile does not match the selected recipe')
        with tempfile.TemporaryDirectory(prefix='cpg-pugixml-functional-') as temporary:
            tmp=Path(temporary)
            def run(argv,expected=0):
                argv=list(map(str,argv));cp=subprocess.run(argv,cwd=tmp,env=env,capture_output=True,text=True,timeout=120)
                report['commands'].append({'argv':argv,'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr})
                if cp.returncode!=expected:raise RuntimeError('Unexpected functional command return code')
                return cp
            if args.case=='cli':executable=prefix/'bin/pugixml-cpg-probe'
            else:
                executable=tmp/'consumer';lib=prefix/('lib/libpugixml.'+('a' if args.case=='static' else 'so'))
                run(['/usr/bin/g++','-std=c++17','-O2','-g0','-I'+str(prefix/'include'),recipe/'consumer.cpp',lib,
                     '-Wl,-rpath,'+str(prefix/'lib'),'-o',executable])
            info=json.loads(run([executable,'--info']).stdout)
            if info!={'library_version':'1.15','header_version':1150,'xpath':True,'stl':True,'exceptions':True,'encoding':'char-UTF8'}:
                raise RuntimeError('Compiled consumer feature/version profile differs')
            api=json.loads(run([executable,'--self-test']).stdout)
            if api!=EXPECTED:raise RuntimeError('Incomplete installed C++ functional controls')
            links=run(['/usr/bin/ldd',executable]).stdout
            if 'not found' in links:raise RuntimeError('Unresolved runtime library')
            paths=re.findall(r'^\s*libpugixml\S*\s+=>\s+(\S+)\s+\(',links,re.M)
            if args.case=='static':
                if paths:raise RuntimeError('Static consumer depends on dynamic pugixml')
                selected=[]
            else:
                real=(prefix/'lib/libpugixml.so').resolve(strict=True)
                if len(paths)!=1 or Path(paths[0]).resolve(strict=True)!=real or real.parent!=(prefix/'lib').resolve():
                    raise RuntimeError('Consumer uses a different pugixml library')
                selected=[{'path':str(real),'sha256':sha(real),'bytes':real.stat().st_size}]
            if args.case=='cli':
                invalid=run([executable,'--cpg-invalid-option'],2)
                if 'usage:' not in invalid.stderr:raise RuntimeError('Missing invalid-option diagnostic')
                report['invalid_cli_options_rejected']=1
                report['cli_origin']='Project qualification probe; not a pugixml upstream command'
            report.update(status='passed',api=api,info=info,selected_library=selected)
    except BaseException as error:
        report.update(status='failed',error=f'{type(error).__name__}: {error}');raise
    finally:print(json.dumps(report,indent=2))

if __name__=='__main__':main()
