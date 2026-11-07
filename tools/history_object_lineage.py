#!/usr/bin/env python3
"""Join historical content-named ZIP entries to an original workspace manifest."""
import argparse
from collections import Counter,defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile
from import_archives import safe_relative


def category(path,partition):
    low=path.lower();parts=low.split('/')
    if '.git' in parts or any(x.startswith('.git/') for x in parts):return 'git_state'
    if any(x in low for x in ('evidence/','workspace-evidence/','/runs/','/logs/','/receipts/')) or low.endswith(('.log','.jsonl')):return 'historical_evidence'
    if any(x in low for x in ('dataset','datasets','benchmark','benchmarks','workloads')):return 'dataset_or_benchmark_material'
    if any(x in low for x in ('controller','driver','resource-integrations/')):return 'resource_integration_or_controller'
    if low.startswith('compiler-playground/tests/') or '/tests/' in low:return 'tests_and_fixtures'
    if low.startswith('compiler-playground/src/') or low.startswith('compiler-playground/compiler_playground/'):return 'framework_source'
    if any(x in low for x in ('/tools/','workspace-tools/','/scripts/','/recipes/')):return 'tooling_or_recipe'
    if partition=='payload':return 'other_payload'
    if low.endswith(('.md','.txt','.rst','.pdf')):return 'documentation'
    return 'other_core_or_workspace'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--expected-manifest-sha256',required=True)
    p.add_argument('--history-root',type=Path,required=True);p.add_argument('--framework-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();history=a.history_root.resolve();out=a.output.resolve()
    if out.is_relative_to(history) or out.exists():p.error('Output must be new and outside history')
    with a.manifest.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest!=a.expected_manifest_sha256:raise ValueError('Workspace manifest SHA-256 differs')
    manifest=json.loads(a.manifest.read_text());ledger=json.loads(a.ledger.read_text())
    cards=json.loads((a.framework_root/'src/compiler_playground/dataset_catalog.json').read_text())['datasets']
    aliases=defaultdict(set)
    for card in cards:
        aliases[card['id'].lower()].add(card['id'])
        for resource in card.get('catalog_resource_ids',[]):
            aliases[resource.lower().removeprefix('dataset-ref.')].add(card['id'])
    paths=defaultdict(list)
    for e in manifest['entries']:
        if e.get('type')=='file' and isinstance(e.get('sha256'),str):
            logical=e['path'];item={'path':logical,'partition':e.get('partition'),'bytes':e.get('size'),
                                    'volume':e.get('volume'),'category':category(logical,e.get('partition'))}
            if logical.lower().endswith(('.c','.cc','.cpp','.cxx','.h','.hpp','.sql','.rs','.ll','.mlir','.f','.f90')):
                candidates=sorted({card for part in logical.lower().split('/') for card in aliases.get(part,set())})
                if candidates:
                    item['dataset_source_unit_candidate']=True
                    item['dataset_card_id_candidates']=candidates
            paths[e['sha256']].append(item)
    spec=importlib.util.spec_from_file_location('history_inventory',a.framework_root/'tools/history-inventory.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    files={Path(x['path']).name:x for x in ledger['files']};sources=[]
    for r in ledger['files']:
        if r.get('zip_index_key'):sources.append(('file',r['path'],r['zip_index_key'],[r]))
    for f in ledger['split_families']:
        if f.get('zip_index_key'):sources.append(('split',f['family'],f['zip_index_key'],[files[n] for n in f['parts']]))
    occurrences=[];referenced=set();metadata_issues=[]
    for kind,name,key,parts in sources:
        idx=ledger['zip_indexes'][key]
        if idx['status']!='central_directory_read' or idx.get('duplicate_names') or idx.get('unsafe_names'):continue
        known={(v['path'],v['sha256']) for v in idx.get('known_object_leads',[])}
        paths_on_disk=[history.joinpath(*safe_relative(x['path']).parts) for x in parts]
        if any(p.is_symlink() or not p.is_file() or p.stat().st_size!=r['bytes'] for p,r in zip(paths_on_disk,parts)):
            raise ValueError('Historical source absent or changed size: '+name)
        source=paths_on_disk[0] if kind=='file' else mod.PartsReader(paths_on_disk)
        with zipfile.ZipFile(source) as z:
            supplemental={}
            if 'manifest.json' in z.namelist():
                try:
                    raw=z.read('manifest.json');extra=json.loads(raw);metadata_sha=hashlib.sha256(raw).hexdigest()
                    if not isinstance(extra,dict):raise ValueError('Embedded manifest is not an object')
                    for entry in extra.get('new_entries',[]):
                        if (isinstance(entry,dict) and all(k in entry for k in ('sha256','bytes','path'))
                                and isinstance(entry['path'],str)):
                            dataset_related=('source_card' in entry or 'source_id' in entry or
                                'dataset' in str(entry.get('kind','')).lower() or 'dataset' in entry['path'].lower())
                            supplemental[entry['sha256']]={'path':entry['path'],'partition':None,'bytes':entry['bytes'],
                                'volume':Path(name).name,'category':'dataset_or_benchmark_material' if dataset_related else 'historical_candidate_new_entry',
                                'declaration_manifest_sha256':metadata_sha}
                except (ValueError,UnicodeError,zipfile.BadZipFile) as error:
                    metadata_issues.append({'source':name,'error':type(error).__name__+': '+str(error)})
            for member in z.infolist():
                sha=Path(member.filename).name
                if member.is_dir() or not re.fullmatch(r'[0-9a-f]{64}',sha) or Path(member.filename).parent.name not in {'objects','sha256'}:continue
                if (member.filename,sha) in known:continue
                links=[v for v in paths.get(sha,[]) if v['bytes']==member.file_size]
                if not links and sha in supplemental and supplemental[sha]['bytes']==member.file_size:
                    paths[sha].append(supplemental[sha]);links=[supplemental[sha]]
                volume=Path(name).name
                exact=[v for v in links if v['volume']==volume]
                object_record=manifest.get('objects',{}).get(sha,{})
                canonical_member=member.filename=='objects/'+sha
                if canonical_member and object_record.get('size')==member.file_size and object_record.get('volume')==volume:
                    binding='manifest_declares_this_volume_and_member'
                elif canonical_member and exact and 'declaration_manifest_sha256' not in exact[0]:binding='logical_entry_declares_this_volume_and_member'
                elif canonical_member and exact:binding='embedded_new_entry_declares_member_sha_and_size'
                elif links:binding='sha_and_size_logical_path_lead_only'
                else:binding='unmapped'
                if links:referenced.add(sha)
                occurrences.append({'source':name,'kind':kind,'member':member.filename,'bytes':member.file_size,
                                    'sha256_from_name':sha,'binding':binding,'logical_path_count':len(links)})
    linked={sha:paths[sha] for sha in sorted(referenced)}
    result={'schema_version':1,'inventory_sha256':ledger['inventory_sha256'],'workspace_manifest_sha256':digest,
            'scope':'ZIP central directory names and original manifest declarations only. No member payload hash was verified here; taxonomy is path-based and does not confer qualification.',
            'occurrences':occurrences,'logical_paths_by_sha256':linked,'embedded_manifest_issues':metadata_issues}
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'occurrences':len(occurrences),'binding':dict(Counter(x['binding'] for x in occurrences)),
                      'distinct_matched_sha256':len(linked),
                      'logical_path_categories':dict(Counter(v['category'] for rows in linked.values() for v in rows)),
                      'dataset_source_unit_candidates':sum(bool(v.get('dataset_source_unit_candidate')) for rows in linked.values() for v in rows)}))

if __name__=='__main__':main()
