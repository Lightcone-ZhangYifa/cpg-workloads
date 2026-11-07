#!/usr/bin/env python3
"""Index historical ZIP central directories without extracting or executing members.

The supplied inventory supplies already computed SHA-256 identities. The ledger
is a list of leads, not qualification or an assertion of member completeness.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile

from import_archives import safe_relative

CANDIDATE = re.compile(r'\.cpg(?:pkg|recipe)(?:\.|$)', re.I)


def index_zip(source):
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            names = [m.filename for m in members]
            unsafe = []
            for name in names:
                try:
                    safe_relative(name.rstrip('/'))
                except ValueError:
                    unsafe.append(name)
            return {'status': 'central_directory_read', 'member_count': len(names),
                    'duplicate_names': [n for n, count in Counter(names).items() if count > 1],
                    'unsafe_names': unsafe,
                    'cpg_name_leads': [{'path': m.filename, 'bytes': m.file_size, 'crc32': '%08x' % m.CRC}
                                       for m in members if not m.is_dir() and CANDIDATE.search(m.filename)],
                    'manifest_name_leads': [m.filename for m in members if not m.is_dir()
                        and 'manifest' in Path(m.filename).name.lower() and m.file_size <= 64 * 1024 * 1024],
                    'payload_crc_verified': False}
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        return {'status': 'unreadable', 'error': str(e), 'payload_crc_verified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--history-root', type=Path, required=True)
    p.add_argument('--framework-root', type=Path, required=True)
    p.add_argument('--workloads-root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    a = p.parse_args()
    raw = a.inventory.read_bytes(); inventory_sha = hashlib.sha256(raw).hexdigest(); inv = json.loads(raw)
    root = a.history_root.resolve(); output = a.output.resolve()
    if output.is_relative_to(root): p.error('Output must be outside historical input')
    if inv['summary']['hashes_computed'] != len(inv['files']): p.error('Inventory requires file SHA-256s')
    cache = {}
    if a.resume and output.exists():
        old = json.loads(output.read_text())
        if old['inventory_sha256'] != inventory_sha: p.error('Resume inventory identity changed')
        cache = old.get('zip_indexes', {})
    elif output.exists(): p.error('Output exists; use --resume')
    module_spec = importlib.util.spec_from_file_location('history_inventory', a.framework_root/'tools/history-inventory.py')
    module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
    references = {}
    def collect_origins(value, filename):
        if isinstance(value, dict):
            if isinstance(value.get('sha256'), str) and ('archive' in value or 'filename' in value):
                references.setdefault(value['sha256'], set()).add(filename)
            for child in value.values(): collect_origins(child, filename)
        elif isinstance(value, list):
            for child in value: collect_origins(child, filename)
    for folder in ('imports', 'artifacts', 'historical-snapshots', 'recipe-snapshots', 'revisions'):
        for path in (a.workloads_root / 'catalog' / folder).glob('*.json'):
            collect_origins(json.loads(path.read_text()), path.relative_to(a.workloads_root).as_posix())
    rows=[]; lookup={}
    for row in inv['files']:
        rel = safe_relative(row['path']); path = root.joinpath(*rel.parts)
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row['bytes']:
            raise ValueError('Inventory path absent or changed size: ' + row['path'])
        lookup.setdefault(path.name, []).append(path)
        result={'path':row['path'], 'bytes':row['bytes'], 'sha256':row['sha256'],
                'category':row.get('category'), 'disposition':'pending_review',
                'catalog_origin_references':sorted(references.get(row['sha256'], set()))}
        if row.get('zip_index',{}).get('status') == 'central_directory_read':
            key='file:'+row['sha256']
            if key not in cache: cache[key]=index_zip(path)
            result['zip_index_key']=key
        rows.append(result)
    families=[]
    for family in inv['split_families']:
        entry={'family':family['family'], 'parts':family['parts'], 'disposition':'pending_review'}
        if family.get('zip_index'):
            paths=[]
            for name in family['parts']:
                if len(lookup.get(name,[])) != 1: raise ValueError('Split part identity ambiguous: '+name)
                paths.append(lookup[name][0])
            key='split:'+hashlib.sha256(json.dumps([next(x['sha256'] for x in rows if Path(x['path']).name==p.name) for p in paths]).encode()).hexdigest()
            if key not in cache: cache[key]=index_zip(module.PartsReader(paths))
            entry['zip_index_key']=key
        families.append(entry)
    result={'schema_version':1,'inventory_sha256':inventory_sha,'files':rows,'split_families':families,'zip_indexes':cache,
            'scope':'Metadata leads only; names and CRCs are not verified package identities or qualification. All inputs remain pending until explicit review.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.name+'.tmp')
    if temporary.exists(): raise FileExistsError(temporary)
    with temporary.open('x') as f: json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    temporary.replace(output)
    print(json.dumps({'files':len(rows),'split_families':len(families),'unique_zip_indexes':len(cache),
        'zip_status':dict(Counter(x['status'] for x in cache.values())),
        'files_with_catalog_origin_references':sum(bool(x['catalog_origin_references']) for x in rows),
        'cpg_member_name_leads':sum(len(x.get('cpg_name_leads',[])) for x in cache.values())}))


if __name__ == '__main__': main()
