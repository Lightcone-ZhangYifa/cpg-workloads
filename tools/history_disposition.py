#!/usr/bin/env python3
"""Generate a per-input review disposition from historical and intake receipts."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger',type=Path,required=True);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--nonzip-state',type=Path)
    p.add_argument('--other-state',type=Path)
    p.add_argument('--prefix-state',type=Path)
    p.add_argument('--lineage-state',type=Path);p.add_argument('--unknown-cases',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Output already exists')
    ledger=json.loads(a.ledger.read_text());state=json.loads(a.state.read_text())
    if ledger['inventory_sha256']!=state['inventory_sha256']:p.error('Inventory identities differ')
    nonzip={}
    if a.nonzip_state:
        value=json.loads(a.nonzip_state.read_text())
        if value['inventory_sha256']!=ledger['inventory_sha256']:p.error('Non-ZIP inventory identity differs')
        nonzip=value['streams']
    others={}
    if a.other_state:
        value=json.loads(a.other_state.read_text())
        if value['inventory_sha256']!=ledger['inventory_sha256']:p.error('Other-file inventory identity differs')
        others={x['path']:x for x in value['files']}
    prefix=json.loads(a.prefix_state.read_text()) if a.prefix_state else None
    lineage=defaultdict(list);cases=defaultdict(list)
    if a.lineage_state:
        value=json.loads(a.lineage_state.read_text())
        if value['inventory_sha256']!=ledger['inventory_sha256']:p.error('Lineage inventory identity differs')
        for row in value['occurrences']:lineage[(row['kind'],row['source'])].append(row['binding'])
    if a.unknown_cases:
        value=json.loads(a.unknown_cases.read_text())
        if value['inventory_sha256']!=ledger['inventory_sha256']:p.error('Case inventory identity differs')
        for row in value['cases']:cases[row['source']].append(row['status'])
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
        if path in nonzip:item['nonzip_stream_status']=nonzip[path]['status']
        if path in others:item['other_file_kind']=others[path]['kind']
        direct=grouped.get(('standalone',path),[])
        if family:
            idx=ledger['zip_indexes'].get(family.get('zip_index_key'),{})
            item['split_family']=family['family'];item['member_outcomes']=dict(Counter(grouped.get(('split',family['family']),[])))
            item['object_lineage_bindings']=dict(Counter(lineage.get(('split',family['family']),[])))
            item['unknown_case_outcomes']=dict(Counter(cases.get(family['family'],[])))
            if 'worker-083-delta' in family['family'] and idx.get('status')=='unreadable':
                if prefix and prefix.get('archive_complete') is False:
                    item.update(disposition='incomplete_zip_prefix_partially_recovered',
                        recovered_member_outcomes=dict(Counter(x['status'] for x in prefix['results'])),
                        unrecovered_members=[x['path'] for x in prefix['unrecovered']],
                        reason='Complete prefix members recovered and checked individually; full central directory and remaining members are unavailable.')
                else:
                    item.update(disposition='incomplete_zip_family_pending',reason='No readable central directory; terminal part completeness not established.')
            elif not family.get('zip_index_key'):
                stream=nonzip.get(family['family'],{})
                item['stream_status']=stream.get('status','not_inspected')
                item.update(disposition='non_zip_split_stream_recorded' if stream.get('status')=='gzip_tar_stream_read' else 'non_zip_split_family_pending',
                    reason='Original parts retained; see stream status. Toolchain function and external completeness remain separate.')
            elif idx.get('status')!='central_directory_read':
                item.update(disposition='unreadable_split_family_pending',reason='Original parts retained; no readable ZIP central directory.')
            else:
                item.update(disposition='split_zip_retained_with_unresolved_members',reason='Selected members have individual outcomes; other members and dependency evidence remain to review.')
        elif direct:
            item['direct_outcomes']=dict(Counter(direct));item.update(
                disposition='standalone_member_in_progress' if 'started' in direct else 'standalone_member_has_recorded_outcome',
                reason='See exact member outcomes; a held or failed outcome remains pending.')
        elif path in nonzip:
            stream=nonzip[path];item['stream_status']=stream['status']
            item.update(disposition='non_zip_stream_recorded' if stream['status']=='gzip_tar_stream_read' else 'non_zip_stream_pending',
                        reason='Original archive retained; no installation or functional qualification inferred.')
        elif row.get('zip_index_key'):
            idx=ledger['zip_indexes'][row['zip_index_key']];outcomes=grouped.get(('file',path),[])
            item.update(disposition='zip_retained_with_unresolved_members',reason='ZIP central directory indexed; nonselected, nested and unnamed members remain to review.',
                central_directory_status=idx['status'],member_count=idx.get('member_count'),
                named_cpg_leads=len(idx.get('cpg_name_leads',[])),object_name_count=idx.get('object_name_count',0),
                known_object_leads=len(idx.get('known_object_leads',[])),member_outcomes=dict(Counter(outcomes)),
                object_lineage_bindings=dict(Counter(lineage.get(('file',path),[]))),
                unknown_case_outcomes=dict(Counter(cases.get(path,[]))))
        elif low.endswith(('.md','.txt','.json','.jsonl','.csv','.yaml','.yml','.sha256','.xml','.html','.pdf','.png','.xlsx','.log','.jsonl.gz')):
            item.update(disposition='historical_metadata_retained',reason='Original file and recorded SHA remain in historical input; content-level reconciliation may still be pending.')
        elif low.endswith('.git.bundle'):
            item.update(disposition='historical_git_delivery_retained',reason='Original Git bundle bytes retained; contained revisions require separate inspection.')
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
