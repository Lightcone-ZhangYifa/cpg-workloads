#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--prefix',required=True,type=Path)
a=p.parse_args();dest=a.prefix/'share/openmp-vv'
shutil.copytree(a.source,dest)
rows=[]
for path in sorted((dest/'tests').rglob('*')):
    if not path.is_file() or path.suffix.lower() not in ('.c','.cpp','.f90','.f','.f95'):continue
    rel=path.relative_to(dest).as_posix();text=path.read_text(errors='replace')
    version=rel.split('/')[1]
    if not re.fullmatch(r'\d+\.\d+',version):continue
    rows.append(dict(path=rel,specification_version=version,language='Fortran' if path.suffix.lower().startswith('.f') else 'C++' if path.suffix=='.cpp' else 'C',
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size,
                     has_target_directive=bool(re.search(r'(?im)(?:#\s*pragma\s+omp|!\$omp)\s+target\b',text)),
                     expected=dict(compile_returncode=0,run_returncode=0,skip_returncode=(-667)%256,output_contract='upstream OMPVV assertions/OMPVV_REPORT_AND_RETURN; source-specific behavior retained'),
                     execution_status='not_run'))
(a.prefix/'share/openmp-vv-index.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps({'status':'installed','indexed_tests':len(rows),'source_modified':False}))
