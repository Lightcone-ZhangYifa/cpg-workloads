#!/usr/bin/env python3
"""Verify and statically retain recovered complete members of an incomplete ZIP prefix."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

from history_intake import check_template, identity, worker_labeled_id
from import_archives import import_package, sha256, write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recovery',type=Path,required=True);p.add_argument('--history-root',type=Path,required=True)
    p.add_argument('--framework-root',type=Path,required=True);p.add_argument('--workloads-root',type=Path,required=True)
    p.add_argument('--cold-root',type=Path,required=True);p.add_argument('--scratch',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();history=a.history_root.resolve();recovery=a.recovery.resolve();root=a.workloads_root.resolve()
    if any(p.resolve().is_relative_to(history) for p in (a.cold_root,a.scratch,a.output)):p.error('Outputs must be outside historical input')
    sys.path.insert(0,str(a.framework_root.resolve()/'src'))
    from compiler_playground.packages import verify_package
    comparison=json.loads((recovery/'artifact-index-comparison.json').read_text());receipt=json.loads((recovery/'receipt.json').read_text())
    if comparison['archive_complete'] is not False:raise ValueError('Expected explicitly incomplete archive')
    prefix=hashlib.sha256();prefix_bytes=0
    for part in comparison['parts']:
        source=history/part['path'];h=hashlib.sha256();n=0
        with source.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block);prefix.update(block);n+=len(block);prefix_bytes+=len(block)
        if n!=part['bytes'] or h.hexdigest()!=part['sha256']:raise ValueError('Historical part identity differs')
    if prefix.hexdigest()!=comparison['family_concat_sha256']:raise ValueError('Available-prefix identity differs')
    index_blob=next(x for x in receipt['members'] if x['name']=='delta/artifact-index.json')
    if sha256(recovery/index_blob['blob'])!=comparison['artifact_index_sha256']:raise ValueError('Recovered artifact index differs')
    index=json.loads((recovery/index_blob['blob']).read_text())
    indexed={x['path']:x for x in index['accepted']}
    if len(indexed)!=len(index['accepted']) or len(indexed)!=comparison['accepted_count']:
        raise ValueError('Recovered artifact index is not unique and complete')
    # The independent comparison supplies original indexed identities; it must agree with recovered members.
    members={x['name']:x for x in receipt['members']};results=[]
    output={'schema_version':1,'prefix_sha256':comparison['family_concat_sha256'],'archive_complete':False,
            'unrecovered':comparison['unrecovered'],'stop':comparison['stop'],'results':results}
    if a.output.exists():raise ValueError('Output exists; inspect it before another intake')
    cold=a.cold_root/'packages/sha256';cold.mkdir(parents=True,exist_ok=True);a.scratch.mkdir(parents=True,exist_ok=True)
    for item in comparison['recovered']:
        if not item['matches'] or item['sha256']!=item['index_sha256'] or item['bytes']!=item['index_bytes']:
            raise ValueError('Comparison did not establish indexed member identity')
        original=indexed.get(item['path'])
        if not original or original['sha256']!=item['sha256'] or original['bytes']!=item['bytes']:
            raise ValueError('Recovered member differs from the original artifact index')
        evidence=members[item['path']]
        if (evidence['sha256']!=item['sha256'] or evidence['bytes']!=item['bytes'] or
                evidence['verification']!='deflate_eof_and_descriptor_crc32_and_sizes'):
            raise ValueError('Recovered member evidence differs')
        blob=recovery/item['blob'];result={'path':item['path'],'sha256':item['sha256'],'status':'started'}
        results.append(result);write_json(a.output,output)
        try:
            checked=verify_package(blob)
            if checked['sha256']!=item['sha256'] or checked['bytes']!=item['bytes']:raise ValueError('Package bytes differ')
            manifest=checked['manifest'];digest=checked['sha256'];result.update(id=manifest['package']['id'],method=manifest['method'])
            if (manifest['package']['id']!=original['resource_id'] or manifest['method']!=original['method']
                    or manifest['manifest_sha256']!=original['manifest_sha256']):
                raise ValueError('Package manifest differs from original artifact index')
            obj=cold/(digest+'.cpgpkg.tar.gz')
            if not obj.exists():
                with blob.open('rb') as inp,obj.open('xb') as out:shutil.copyfileobj(inp,out)
            if obj.is_symlink() or obj.stat().st_size!=item['bytes'] or sha256(obj)!=digest:raise ValueError('Cold mirror differs')
            origin={'archive':'cpg-20261101-worker-083-delta-v001.zip','sha256':comparison['family_concat_sha256'],
                    'bytes':prefix_bytes,'member':item['path'],'scope':'available_prefix_only_not_a_complete_archive',
                    'member_header_offset':item['header_offset'],'member_end_offset':item['end_offset'],
                    'artifact_index_sha256':comparison['artifact_index_sha256'],'part_sha256s':[x['sha256'] for x in comparison['parts']]}
            existing=root/'catalog/artifacts'/(digest+'.json')
            if existing.exists():
                old=json.loads(existing.read_text())
                if any(old.get(k)!=v for k,v in identity(manifest,digest,item['bytes']).items()):raise ValueError('Existing identity conflict')
                if origin not in old['origins']:old['origins'].append(origin);write_json(existing,old)
                result['status']='existing_artifact_origin_recorded'
            else:
                with tempfile.TemporaryDirectory(prefix='prefix-',dir=a.scratch) as td:
                    staged=Path(td);import_package(blob,staged,origin,static_trust=True)
                    record=json.loads((staged/'catalog/artifacts'/(digest+'.json')).read_text());template=staged/record['template']
                    hold=check_template(template);destination=root/record['template']
                    if worker_labeled_id(record['id']):result['status']='held_worker_labeled_original_identity'
                    elif hold:result['status']=hold
                    elif destination.exists():result['status']='held_existing_template_without_record'
                    else:
                        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(template,destination,symlinks=True)
                        write_json(existing,record);result.update(status='new_artifact_recorded',release_eligible=record['release_eligible'])
        except Exception as e:result.update(status='error',error=type(e).__name__+': '+str(e))
        write_json(a.output,output);print(json.dumps(result),flush=True)

if __name__=='__main__':main()
