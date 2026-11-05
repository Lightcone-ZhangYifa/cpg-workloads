#!/usr/bin/env python3
"""Independent exact frozen source supplement verification after CPG installation."""
import argparse,hashlib,json,os,stat,sys
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--prefix',type=Path,required=True)
p.add_argument('--manifest',type=Path,required=True)
a=p.parse_args()
report={'status':'failed'}
try:
    d=json.loads(a.manifest.read_text())
    assert d['schema_version']==1 and d['source_count']==1
    file=d['files'][0]
    target=a.prefix/Path(file['path'])
    assert target.is_file() and not target.is_symlink()
    st=target.stat()
    assert st.st_size==file['bytes'] and stat.S_IMODE(st.st_mode)==file['mode']
    with target.open('rb') as f:
        raw=f.read()
    assert hashlib.sha256(raw).hexdigest()==file['sha256']
    assert len(raw.decode('utf-8').strip())>50
    report={'status':'passed','resource_id':d['resource_id'],'sha256':file['sha256'],
            'bytes':st.st_size,'mode':stat.S_IMODE(st.st_mode),
            'qualification_scope':'single_pinned_source_supplement_data_only'}
except BaseException as exc:
    report.update(error_type=type(exc).__name__,error=str(exc))
print(json.dumps(report,ensure_ascii=False,sort_keys=True))
sys.exit(0 if report['status']=='passed' else 1)
