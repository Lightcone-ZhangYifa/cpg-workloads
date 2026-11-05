#!/usr/bin/env python3
"""Availability only: validate the exact static content and policy boundary."""
import argparse,hashlib,json,pathlib

def main():
    p=argparse.ArgumentParser();p.add_argument('--prefix',type=pathlib.Path,required=True);args=p.parse_args()
    root=args.prefix.resolve()
    index=json.loads((root/'material-index.json').read_text())
    policy=json.loads((root/'POLICY.json').read_text())
    assert policy['collection_enabled'] is False
    assert policy['upstream_execution_enabled'] is False
    assert policy['system_analyzer_policy']=='perf-only'
    lock=json.loads((root/'source-lock.json').read_text())
    assert lock['logical_resource_id']==index['logical_resource_id']
    assert lock['reference_page_bodies_redistributed'] is False
    for row in lock['original_archives']:
        f=root/row['path'];assert f.resolve().is_relative_to(root) and f.is_file() and not f.is_symlink()
        assert f.stat().st_size==row['bytes'],row['path']+' byte count'
        assert hashlib.sha256(f.read_bytes()).hexdigest()==row['sha256'],row['path']+' SHA256'
    assert len(lock['original_archives'])==index['archive_count']
    members=json.loads((root/'archive-members.json').read_text())
    assert len(members)==index['archive_member_count']
    available={(x['archive'],x['member']) for x in members if x['type']=='file'}
    refs=[json.loads(x) for x in (root/'reference-text.jsonl').read_text().splitlines()]
    assert len(refs)==index['reference_document_count']
    for r in refs:
        assert (r['archive'],r['member']) in available
        assert hashlib.sha256(r['text'].encode()).hexdigest()==r['sha256']
    for topic in index['topics']:
        if index['archive_count']:assert topic['source_members'],topic['name']
        for r in topic['source_members']:assert (r['archive'],r['member']) in available
    for name in ('MATERIALS.md','LICENSES.txt','inspect_material.py'):
        assert (root/name).is_file() and (root/name).stat().st_size>0
    if index['baseline_definition_sha256']:
        b=root/'baseline-package.json'
        assert hashlib.sha256(b.read_bytes()).hexdigest()==index['baseline_definition_sha256']
    print(json.dumps({'status':'passed','logical_resource_id':index['logical_resource_id'],'qualification':'availability-only','archives_verified':len(lock['original_archives']),'archive_members':len(members),'reference_documents':len(refs),'functional_execution':'not_run','collection_performed':False},ensure_ascii=False,sort_keys=True))

if __name__=='__main__':main()
