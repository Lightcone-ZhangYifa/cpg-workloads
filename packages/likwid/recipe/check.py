#!/usr/bin/env python3
"""Read-only LIKWID topology, query interfaces and installed C consumers."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def validate(text):
    if not re.search(r'(?:Threads\s+per\s+core|HWThread|Hardware Thread)',text,re.IGNORECASE) or not re.search(r'CPU\s+(?:name|type)|Sockets?\s*:',text,re.IGNORECASE):
        raise ValueError('LIKWID returned no CPU identity/thread topology')


def validate_api(text,prefix):
    values=[json.loads(line[len('CPG_JSON='):]) for line in text.splitlines() if line.startswith('CPG_JSON=')]
    if len(values)!=1:raise ValueError('The installed API client did not emit exactly one result')
    value=values[0]
    for key in ('hardware_threads','sockets','numa_nodes'):
        if type(value.get(key)) is not int or value[key]<1:raise ValueError('Empty API topology: '+key)
    if value.get('group_roundtrip') is not True or value.get('counter_collection_qualified') is not False:
        raise ValueError('The read-only API operation contract was not satisfied')
    if Path(value.get('library_path','')).resolve(strict=True)!=(prefix/'lib/liblikwid.so').resolve(strict=True):
        raise ValueError('The consumer loaded another LIKWID installation')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',type=Path,required=True)
    parser.add_argument('--check',choices=('topology','api','consumer','queries'),default='topology')
    args=parser.parse_args();commands=[]
    result={'status':'failed','check':'likwid-'+args.check,'commands':commands,'counter_collection_qualified':False,'daemon_started':False}
    try:
        prefix=args.prefix.resolve(strict=True)
        env=dict(os.environ,LC_ALL='C',LD_LIBRARY_PATH=str(prefix/'lib'))
        env.pop('LD_PRELOAD',None)
        def run(argv,expected=0):
            p=subprocess.run([str(x) for x in argv],env=env,capture_output=True,text=True,timeout=90)
            commands.append({'argv':[str(x) for x in argv],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
            if expected==0 and p.returncode!=0:raise ValueError('LIKWID operation returned nonzero: '+str(argv[0]))
            if expected!=0 and p.returncode==0:raise ValueError('Invalid query unexpectedly succeeded')
            return p.stdout
        if args.check=='topology':
            validate(run([prefix/'bin/likwid-topology']))
            csv=run([prefix/'bin/likwid-topology','-O'])
            if 'STRUCT' not in csv or 'HWThread' not in csv:raise ValueError('CSV topology fields are missing')
            result['csv_topology']=csv
        elif args.check=='api':
            result['api']=validate_api(run([prefix/'bin/likwid-api-check']),prefix)
        elif args.check=='consumer':
            with tempfile.TemporaryDirectory(prefix='cpg-likwid-consumer-') as temporary:
                binary=Path(temporary)/'consumer'
                run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(prefix/'include'),
                     prefix/'share/compiler-playground/likwid/api-check.c','-L'+str(prefix/'lib'),
                     '-Wl,-rpath,'+str(prefix/'lib'),'-llikwid','-ldl','-o',binary])
                result['api']=validate_api(run([binary]),prefix)
        else:
            kernels=run([prefix/'bin/likwid-bench','-a'])
            if not all(word in kernels.lower() for word in ('copy','triad')):raise ValueError('Kernel enumeration lacks expected upstream kernels')
            events=run([prefix/'bin/likwid-perfctr','-e'])
            counts=re.findall(r'This architecture has (\d+) (counters|events)',events)
            if len(counts)!=2 or any(int(count)<1 for count,_ in counts):raise ValueError('Event/counter definition enumeration is empty')
            groups=run([prefix/'bin/likwid-perfctr','-a'])
            if 'Group name' not in groups or len(groups.splitlines())<4:raise ValueError('Performance group enumeration is empty')
            run([prefix/'bin/likwid-topology','--cpg-invalid-option'],expected=1)
            result['definition_counts']={kind:int(count) for count,kind in counts}
        result['status']='passed'
    except (OSError,ValueError,subprocess.SubprocessError) as error:result['reason']=str(error)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
