#!/usr/bin/env python3
"""Validate PAPI discovery and C/Fortran clients without starting any counter."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def validate(text):
    if not re.search(r'(?:PAPI Version|Available components)',text,re.IGNORECASE):raise ValueError('PAPI did not initialize and list components')
    if 'Compiled-in components:' not in text or not re.search(r'^Name:\s+\S+',text,re.MULTILINE):raise ValueError('PAPI output contains no component identity')


def validate_api(text,prefix):
    values=[json.loads(line[len('CPG_JSON='):]) for line in text.splitlines() if line.startswith('CPG_JSON=')]
    if len(values)!=1:raise ValueError('The PAPI API client did not emit exactly one result')
    value=values[0]
    names=[row.get('name') for row in value.get('components',[])]
    if set(names)!={'perf_event','perf_event_uncore','rapl'} or len(names)!=3:raise ValueError('Original compiled component set was not preserved')
    for key in ('empty_eventset_lifecycle','invalid_event_rejected','monotonic_time'):
        if value.get(key) is not True:raise ValueError('The API operation failed: '+key)
    if value.get('counter_collection_qualified') is not False:raise ValueError('Discovery cannot qualify counter measurement')
    if Path(value.get('library_path','')).resolve(strict=True)!=(prefix/'lib/libpapi.so').resolve(strict=True):
        raise ValueError('The API client loaded another PAPI installation')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',type=Path,required=True)
    parser.add_argument('--check',choices=('components','api','consumer','fortran'),default='components')
    args=parser.parse_args();commands=[]
    result={'status':'failed','check':'papi-'+args.check,'commands':commands,'counter_collection_qualified':False}
    try:
        prefix=args.prefix.resolve(strict=True)
        env=dict(os.environ,LC_ALL='C',LD_LIBRARY_PATH=str(prefix/'lib')+(os.pathsep+os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else ''))
        env.pop('LD_PRELOAD',None)
        def run(argv):
            p=subprocess.run([str(x) for x in argv],env=env,capture_output=True,text=True,timeout=90)
            commands.append({'argv':[str(x) for x in argv],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
            if p.returncode:raise ValueError('PAPI operation returned nonzero: '+str(argv[0]))
            return p.stdout
        if args.check=='components':
            text=run([prefix/'bin/papi_component_avail']);validate(text);result['component_report']=text
        elif args.check=='api':result['api']=validate_api(run([prefix/'bin/papi-api-check']),prefix)
        else:
            with tempfile.TemporaryDirectory(prefix='cpg-papi-consumer-') as temporary:
                binary=Path(temporary)/'consumer'
                if args.check=='consumer':
                    run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(prefix/'include'),
                         prefix/'share/compiler-playground/papi/api-check.c','-L'+str(prefix/'lib'),
                         '-Wl,-rpath,'+str(prefix/'lib'),'-lpapi','-ldl','-o',binary])
                    result['api']=validate_api(run([binary]),prefix)
                else:
                    compiler=os.environ.get('CPG_GFORTRAN','gfortran')
                    run([compiler,'-I'+str(prefix/'include'),prefix/'share/compiler-playground/papi/api-check.f90',
                         '-L'+str(prefix/'lib'),'-Wl,-rpath,'+str(prefix/'lib'),'-lpapi','-o',binary])
                    if 'PAPI Fortran initialization/eventset lifecycle passed' not in run([binary]):
                        raise ValueError('The Fortran consumer did not execute the declared operations')
                    result['fortran_eventset_lifecycle']='passed'
        result['status']='passed'
    except (OSError,ValueError,subprocess.SubprocessError) as error:result['reason']=str(error)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
