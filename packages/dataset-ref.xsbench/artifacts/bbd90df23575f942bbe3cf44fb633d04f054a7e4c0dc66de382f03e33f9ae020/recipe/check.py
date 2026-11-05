#!/usr/bin/env python3
"""Functional XSBench CPU OpenMP qualification from upstream fixed Small validation oracle."""
import argparse,os,re,subprocess,sys,json,hashlib,platform
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);x=p.parse_args()
prog=x.prefix/'bin/XSBench';assert prog.is_file() and os.access(prog,os.X_OK)
assert (x.prefix/'share/doc/XSBench/LICENSE').is_file()
results=[]
for threads in (2,):
    cmd=[str(prog),'-s','small','-t',str(threads)]
    proc=subprocess.run(cmd,env={**os.environ,'LC_ALL':'C','OMP_NUM_THREADS':str(threads)},capture_output=True,text=True,timeout=120,cwd=x.prefix)
    output=proc.stdout+proc.stderr
    proof={ 'threads':threads,'exit_code':proc.returncode,'oracle_expected':941535, 'oracle_reported':None,'lookups_expected':17000000,'lookups_reported':None, 'upstream_validity_token': '(Valid)' in output, 'warning_present':'WARNING' in output,'sha256_stdout':hashlib.sha256(proc.stdout.encode()).hexdigest()}
    m=re.search(r'Verification checksum:\s*(\d+)\s*\(([^)]+)\)',output)
    lookups=re.findall(r'Lookups:\s*([\d,]+)',output);lookup=lookups[-1] if lookups else None
    assert m and lookup and proc.returncode==0,(threads, proc.returncode,output[-700:])
    proof['oracle_reported']=int(m.group(1));proof['lookups_reported']=int(lookup.replace(',',''))
    assert proof['oracle_reported']==941535 and m.group(2)=='Valid' and not proof['warning_present'] and proof['lookups_reported']==17000000,proof
    assert re.search(r'Threads:\s*'+str(threads)+r'\b',output)
    results.append(proof)
print(json.dumps({'status':'passed','scope':'native_cpu_openmp_upstream_small_history_reference_not_official_benchmark','resource_id':'dataset-ref.xsbench','checks':results,'bin_sha256':hashlib.sha256(prog.read_bytes()).hexdigest(),'host':platform.platform(),'physical_target_Ubuntu2404_executed':False,'gpu_or_mpi_qualified':False,'dataset_interface_qualified':False},sort_keys=True))
