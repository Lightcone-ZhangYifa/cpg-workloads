#!/usr/bin/env python3
"""Read shallow ZIP manifests as historical identity leads, without executing them."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import zipfile

from import_archives import safe_relative

SHA=re.compile(r'[0-9a-f]{64}\Z')


def hashes(value):
    if isinstance(value,dict):
        for key,child in value.items():
            if (isinstance(key,str) and (key in ('sha256','sha256sum') or key.endswith('_sha256'))
                    and isinstance(child,str) and SHA.fullmatch(child)):
                yield child
            yield from hashes(child)
    elif isinstance(value,list):
        for item in value:yield from hashes(item)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger',type=Path,required=True);p.add_argument('--history-root',type=Path,required=True)
    p.add_argument('--framework-root',type=Path,required=True);p.add_argument('--workloads-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--max-manifest-bytes',type=int)
    p.add_argument('--max-total-bytes',type=int)
    a=p.parse_args();history=a.history_root.resolve();output=a.output.resolve()
    if output.is_relative_to(history):p.error('Output must be outside historical input')
    if output.exists():p.error('Output already exists')
    ledger=json.loads(a.ledger.read_text());spec=importlib.util.spec_from_file_location('history_inventory',a.framework_root/'tools/history-inventory.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    catalog={p.stem for p in (a.workloads_root/'catalog/artifacts').glob('*.json') if SHA.fullmatch(p.stem)}
    files={Path(x['path']).name:x for x in ledger['files']};sources=[]
    for row in ledger['files']:
        if row.get('zip_index_key'):sources.append(('file',row['path'],row['zip_index_key'],[row]))
    for family in ledger['split_families']:
        if family.get('zip_index_key'):
            sources.append(('split',family['family'],family['zip_index_key'],[files[x] for x in family['parts']]))
    outputs=[];used=0
    for kind,name,key,parts in sources:
        idx=ledger['zip_indexes'][key]
        if idx['status']!='central_directory_read' or idx.get('duplicate_names') or idx.get('unsafe_names'):continue
        leads=[n for n in idx.get('manifest_name_leads',[]) if n.count('/')<=1 and n.lower().endswith('.json')]
        if not leads:continue
        paths=[history.joinpath(*safe_relative(x['path']).parts) for x in parts]
        if any(p.is_symlink() or not p.is_file() or p.stat().st_size!=r['bytes'] for p,r in zip(paths,parts)):
            raise ValueError('Historical source absent or size changed: '+name)
        source=paths[0] if kind=='file' else module.PartsReader(paths)
        with zipfile.ZipFile(source) as z:
            for member in leads:
                info=z.getinfo(member);row={'source':name,'kind':kind,'member':member,'bytes':info.file_size}
                if ((a.max_manifest_bytes is not None and info.file_size>a.max_manifest_bytes) or
                        (a.max_total_bytes is not None and used+info.file_size>a.max_total_bytes)):
                    row['status']='deferred_metadata_budget';outputs.append(row);continue
                try:
                    raw=z.read(info);used+=len(raw);value=json.loads(raw);declared=set(hashes(value));matches=sorted(declared & catalog)
                    row.update(status='metadata_read',member_sha256=hashlib.sha256(raw).hexdigest(),
                               declared_sha_count=len(declared),catalog_artifact_sha_matches=matches,
                               unverified_declared_sha_count=len(declared-set(matches)))
                except (ValueError,UnicodeError,zipfile.BadZipFile) as e:
                    row.update(status='unreadable_metadata',error=type(e).__name__+': '+str(e))
                outputs.append(row)
    result={'schema_version':1,'inventory_sha256':ledger['inventory_sha256'],
      'scope':'Shallow JSON metadata only. Matching a declaration is a lead, not proof the corresponding member exists or has verified bytes. Unselected members remain pending.',
      'metadata_bytes_read':used,'manifests':outputs}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:json.dump(result,f,indent=2,ensure_ascii=False);f.write('\n')
    print(json.dumps({'manifest_records':len(outputs),'status':dict(Counter(x['status'] for x in outputs)),
        'metadata_bytes_read':used,'manifests_with_catalog_sha_leads':sum(bool(x.get('catalog_artifact_sha_matches')) for x in outputs)}))


if __name__=='__main__':main()
