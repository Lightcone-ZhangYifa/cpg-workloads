#!/usr/bin/env python3
"""Generate a per-input review disposition from historical and intake receipts."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger',type=Path,required=True);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Output already exists')
    ledger=json.loads(a.ledger.read_text());state=json.loads(a.state.read_text())
    if ledger['inventory_sha256']!=state['inventory_sha256']:p.error('Inventory identities differ')
    grouped=defaultdict(list)
    for item in state['results'].values():grouped[(item['job']['kind'],item['job']['source'])].append(item['status'])
    families={part:f for f in ledger['split_families'] for part in f['parts']};seen=defaultdict(list)
    for row in ledger['files']:seen[row['sha256']].append(row['path'])
    output=[]
    for row in ledger['files']:
        path=row['path'];name=Path(path).name;low=name.lower();family=families.get(name)
        item={'path':path,'sha256':row['sha256'],'bytes':row['bytes'],'category':row.get('category'),
              'duplicate_file_paths':seen[row['sha256']] if len(seen[row['sha256']])>1 else [],
              'catalog_origin_references':row.get('catalog_origin_references',[])}
        direct=grouped.get(('standalone',path),[])
        if family:
            idx=ledger['zip_indexes'].get(family.get('zip_index_key'),{})
            item['split_family']=family['family'];item['member_outcomes']=dict(Counter(grouped.get(('split',family['family']),[])))
            if 'worker-083-delta' in family['family'] and idx.get('status')=='unreadable':
                item.update(disposition='incomplete_zip_family_pending',reason='No readable central directory; terminal part completeness not established.')
            elif not family.get('zip_index_key'):
                item.update(disposition='non_zip_split_family_pending',reason='Original parts retained; stream format and closure require separate validation.')
            elif idx.get('status')!='central_directory_read':
                item.update(disposition='unreadable_split_family_pending',reason='Original parts retained; no readable ZIP central directory.')
            else:
                item.update(disposition='split_family_mixed_members_pending',reason='Selected members have individual outcomes; other members and dependency evidence remain to review.')
        elif direct:
            item['direct_outcomes']=dict(Counter(direct));item.update(
                disposition='standalone_member_in_progress' if 'started' in direct else 'standalone_member_has_recorded_outcome',
                reason='See exact member outcomes; a held or failed outcome remains pending.')
        elif row.get('zip_index_key'):
            idx=ledger['zip_indexes'][row['zip_index_key']];outcomes=grouped.get(('file',path),[])
            item.update(disposition='zip_mixed_members_pending',reason='ZIP central directory indexed; nonselected, nested and unnamed members remain to review.',
                central_directory_status=idx['status'],member_count=idx.get('member_count'),
                named_cpg_leads=len(idx.get('cpg_name_leads',[])),object_name_count=idx.get('object_name_count',0),
                known_object_leads=len(idx.get('known_object_leads',[])),member_outcomes=dict(Counter(outcomes)))
        elif low.endswith(('.md','.txt','.json','.csv','.yaml','.yml','.sha256','.xml','.html')):
            item.update(disposition='historical_metadata_retained',reason='Original file and recorded SHA remain in historical input; content-level reconciliation may still be pending.')
        else:
            item.update(disposition='unclassified_file_pending',reason='Original bytes retained; source, archive, evidence and qualification require separate review.')
        output.append(item)
    result={'schema_version':1,'inventory_sha256':ledger['inventory_sha256'],'files':output,
      'scope':'Per-file routing and known individual member outcomes; pending mixed archives are not claimed complete or qualified.'}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'files':len(output),'dispositions':dict(Counter(x['disposition'] for x in output)),
                      'duplicate_sha_files':sum(bool(x['duplicate_file_paths']) for x in output)}))

if __name__=='__main__':main()
