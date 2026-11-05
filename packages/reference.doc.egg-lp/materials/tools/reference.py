#!/usr/bin/env python3
"""Read and validate local CPG reference assets. Python standard library only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
        return h.hexdigest()


def local(root: Path, value: str) -> Path:
    rel = PurePosixPath(value)
    if not value or rel.is_absolute() or '..' in rel.parts or '\\' in value or rel.as_posix() != value:
        raise ValueError('noncanonical reference path: ' + str(value))
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
        raise ValueError('symlink reference path: ' + value)
    if not path.is_file():
        raise ValueError('missing reference file: ' + value)
    return path


def load_index(root: Path) -> dict:
    index = json.loads(local(root, 'reference-index.json').read_text(encoding='utf-8'))
    if index.get('schema_version') != 1 or index.get('kind') != 'cpg_reference_index':
        raise ValueError('unsupported reference index')
    if index.get('qualification') != 'material_only':
        raise ValueError('reference index must declare material_only')
    entries = index.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError('empty reference index')
    ids = [r['id'] for r in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate reference IDs')
    return index


def verify(root: Path) -> dict:
    root = root.absolute()
    index = load_index(root)
    inventory = json.loads(local(root, 'file-manifest.json').read_text(encoding='utf-8'))
    expected = inventory['files']
    if len(expected) != len({r['path'] for r in expected}):
        raise ValueError('duplicate file manifest path')
    for row in expected:
        p = local(root, row['path'])
        if p.stat().st_size != row['bytes'] or sha256(p) != row['sha256']:
            raise ValueError('material file identity mismatch: ' + row['path'])
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    allowed = {r['path'] for r in expected} | {'file-manifest.json', '.cpg-prefix.json'}
    unexpected = actual - allowed
    if unexpected:
        raise ValueError('unmanifested files: ' + ', '.join(sorted(unexpected)))
    for entry in index['entries']:
        p = local(root, entry['path'])
        lines = p.read_text(encoding='utf-8').splitlines()
        start, end = entry['line_start'], entry['line_end']
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
            raise ValueError('invalid index line range: ' + entry['id'])
        selected = '\n'.join(lines[start - 1:end])
        if sha256(p) != entry['file_sha256']:
            raise ValueError('index source digest mismatch: ' + entry['id'])
        if hashlib.sha256(selected.encode()).hexdigest() != entry['selection_sha256']:
            raise ValueError('index selection mismatch: ' + entry['id'])
        if entry['anchor'] not in selected:
            raise ValueError('index anchor missing: ' + entry['id'])
        if 'pdf_path' in entry:
            pdf = local(root, entry['pdf_path'])
            if pdf.read_bytes()[:5] != b'%PDF-' or not 1 <= entry['pdf_page'] <= index['pdf_pages']:
                raise ValueError('invalid PDF locator: ' + entry['id'])
    sources = json.loads(local(root, 'source-lock.json').read_text(encoding='utf-8'))
    for row in sources['sources']:
        p = local(root, row['path'])
        if p.stat().st_size != row['bytes'] or sha256(p) != row['sha256']:
            raise ValueError('upstream source lock mismatch: ' + row['id'])
        if not row['url'].startswith('https://') or not row.get('license'):
            raise ValueError('source identity or license missing: ' + row['id'])
    leaves = json.loads(local(root, 'leaf-map.json').read_text(encoding='utf-8'))
    known = {e['id'] for e in index['entries']}
    for row in leaves['leaves']:
        if not row['entry_ids'] or set(row['entry_ids']) - known:
            raise ValueError('leaf map contains unresolved references: ' + row['leaf_id'])
        if row['tool_functional_qualified'] is not False:
            raise ValueError('reference asset cannot grant tool qualification')
    return {'status': 'passed', 'qualification': 'material_only', 'resource_id': index['resource_id'],
            'files_verified': len(expected), 'indexed_locators_verified': len(index['entries']),
            'source_locks_verified': len(sources['sources']), 'leaf_maps_verified': len(leaves['leaves']),
            'upstream_functional_status': 'not_run', 'dataset_status': 'not_applicable'}


def search(root: Path, query: str) -> list[dict]:
    words = query.casefold().split()
    return [entry for entry in load_index(root)['entries']
            if all(word in json.dumps(entry, ensure_ascii=False).casefold() for word in words)]


def show(root: Path, entry_id: str) -> dict:
    entry = next((r for r in load_index(root)['entries'] if r['id'] == entry_id), None)
    if entry is None:
        raise ValueError('unknown reference ID: ' + entry_id)
    p = local(root, entry['path'])
    if sha256(p) != entry['file_sha256']:
        raise ValueError('reference source changed: ' + entry_id)
    lines = p.read_text(encoding='utf-8').splitlines()
    selected = '\n'.join(lines[entry['line_start'] - 1:entry['line_end']])
    if hashlib.sha256(selected.encode()).hexdigest() != entry['selection_sha256']:
        raise ValueError('reference selection changed: ' + entry_id)
    return {**entry, 'text': selected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('verify')
    sub.add_parser('list')
    sub.add_parser('search').add_argument('query')
    sub.add_parser('show').add_argument('id')
    args = parser.parse_args()
    try:
        result = verify(args.root) if args.action == 'verify' else search(args.root, args.query) if args.action == 'search' else show(args.root, args.id) if args.action == 'show' else load_index(args.root)['entries']
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
