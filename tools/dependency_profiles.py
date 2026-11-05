#!/usr/bin/env python3
"""Generate complete immutable dependency contexts from verified public rows.

API: build_profiles(published_rows, source_directory, output_directory,
                    manifest_prefix='profiles') -> dict
The caller supplies rows from verified public release receipts. No network,
package acquisition, build, installation or workload execution occurs here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

GENERATED_BY = 'cpg-dependency-profiles-v1'
SHA = re.compile(r'[0-9a-f]{64}\Z')
ID = re.compile(r'[a-z0-9][a-z0-9.+_-]*\Z')
IDENTITY_FIELDS = ('id', 'version', 'build', 'method', 'target', 'sha256')


def _require(value, message):
    if not value:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _identity(row):
    _require(isinstance(row, dict), 'Package identity must be an object')
    value = {k:row[k] for k in IDENTITY_FIELDS}
    _require(isinstance(value['id'], str) and ID.fullmatch(value['id']), 'Invalid package ID')
    _require(all(isinstance(value[k], str) and value[k] for k in ('version', 'build')), 'Incomplete package version/build')
    _require(value['method'] in {'source', 'binary', 'material', 'wrapper'}, 'Invalid package method')
    _require(isinstance(value['target'], dict) and all(isinstance(value['target'].get(k), str)
        and value['target'][k] for k in ('os', 'arch', 'distribution', 'distribution_version')), 'Incomplete target')
    _require(isinstance(value['sha256'], str) and SHA.fullmatch(value['sha256']), 'Invalid artifact digest')
    return value


def _key(row):
    value = _identity(row)
    value.pop('sha256')
    return _canonical(value)


def _dependencies(row):
    rows = row.get('dependencies')
    _require(isinstance(rows, list), 'Missing dependency list')
    values = [_identity(dep) for dep in rows]
    _require(len({d['sha256'] for d in values}) == len(values), 'Duplicate dependency byte lock')
    return sorted(values, key=_canonical)


def _validate_published(row):
    _identity(row)
    _dependencies(row)
    _require(type(row.get('bytes')) is int and row['bytes'] > 0, 'Missing public artifact byte count')
    _require(isinstance(row.get('manifest_sha256'), str) and SHA.fullmatch(row['manifest_sha256']),
        'Missing public manifest identity')
    address = row.get('download_url')
    _require(isinstance(address, str), 'Missing public download URL')
    parsed = urlsplit(address)
    _require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
        and not parsed.query and not parsed.fragment, 'Expected a stable credential-free public download URL')
    _require(isinstance(row.get('path'), str) and row['path'], 'Missing standard repository artifact path')


def _slug(value, limit=60):
    original = str(value)
    clean = re.sub(r'[^a-zA-Z0-9.+_-]+', '-', original).strip('-.') or 'unknown'
    if clean != original or len(clean) > limit:
        clean = clean[:limit - 13] + '-' + hashlib.sha256(original.encode()).hexdigest()[:12]
    return clean


def _root_name(row):
    return 'package--' + '--'.join([_slug(row['id']), _slug(row['version'], 32),
        _slug(row['build'], 32), row['method'], _slug(row['target']['os'] + '-' + row['target']['arch'], 24),
        row['sha256'][:12]])


def _write_owned(path, value):
    if path.exists():
        _require(not path.is_symlink() and json.loads(path.read_text()).get('profile', {}).get('generated_by') == GENERATED_BY,
            'Refusing to overwrite an unrelated profile file')
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.profile-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
    temporary.chmod(0o644)
    temporary.replace(path)
    return {'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw)}


def _remove_stale_owned(path):
    if path.exists():
        _require(not path.is_symlink() and json.loads(path.read_text()).get('profile', {}).get('generated_by') == GENERATED_BY,
            'Refusing to remove an unrelated profile file')
        path.unlink()


def build_profiles(published_rows, source_directory, output_directory, *, manifest_prefix='profiles'):
    """Write only complete, unambiguous contexts and report every pending SHA."""
    source, output = Path(source_directory), Path(output_directory)
    _require(not source.is_symlink() and source.is_dir(), 'Missing ordinary profile source directory')
    _require(not output.is_symlink() and not any(p.is_symlink() for p in output.absolute().parents),
        'Profile output traverses a symlink')
    output.mkdir(parents=True, exist_ok=True)
    _require(re.fullmatch(r'[a-zA-Z0-9._/-]+', manifest_prefix) and '..' not in Path(manifest_prefix).parts
        and not Path(manifest_prefix).is_absolute(), 'Invalid public profile path prefix')
    public = {}
    for row in published_rows:
        _validate_published(row)
        checksum = row['sha256']
        if checksum in public:
            for key in (*IDENTITY_FIELDS, 'bytes', 'manifest_sha256'):
                _require(public[checksum][key] == row[key], 'The same public archive has inconsistent identity metadata')
            _require(_dependencies(public[checksum]) == _dependencies(row), 'Conflicting public dependency locks')
        else:
            public[checksum] = copy.deepcopy(row)
    catalog = json.loads((source / 'index.json').read_text())
    jobs = []
    for metadata in catalog['profiles']:
        filename = Path(metadata['path']).name
        path = source / filename
        _require(not path.is_symlink() and path.is_file(), 'Missing original context source index')
        raw = path.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == metadata['public_source_sha256'], 'Context source index changed')
        context = json.loads(raw)
        expected = {row['sha256']:row for row in context['packages']}
        _require(len(expected) == len(context['packages']), 'Duplicate source context member')
        jobs.append({'name':'context--' + _slug(metadata['id'], 100), 'kind':'original_context',
            'required':set(expected), 'expected':expected, 'original_context':metadata['id'],
            'original_index_sha256':metadata['original_sha256'], 'root':None})
    closure_path = source / 'canonical-closures.json'
    _require(not closure_path.is_symlink(), 'Canonical closure source is a symlink')
    closures = json.loads(closure_path.read_text())
    for row in closures['roots']:
        root = _identity(row['root'])
        required = set(row['closure_sha256s'])
        _require(root['sha256'] in required and len(required) == len(row['closure_sha256s'])
            and all(isinstance(s, str) and SHA.fullmatch(s) for s in required), 'Invalid canonical closure')
        jobs.append({'name':_root_name(root), 'kind':'canonical_root', 'required':required,
            'expected':{}, 'original_context':row.get('original_profile_membership', []),
            'root':root})
    names = [job['name'] for job in jobs]
    _require(len(names) == len(set(names)), 'Profile output name collision')
    ready, pending = [], []
    for job in jobs:
        destination = output / (job['name'] + '.json')
        missing = sorted(job['required'] - set(public))
        if missing:
            _remove_stale_owned(destination)
            pending.append({'id':job['name'], 'kind':job['kind'], 'missing_sha256s':missing,
                'required_artifact_count':len(job['required'])})
            continue
        rows = [public[sha] for sha in sorted(job['required'])]
        identities = {}
        for row in rows:
            key = _key(row)
            _require(key not in identities or identities[key] == row['sha256'], 'Ambiguous identity inside one dependency context')
            identities[key] = row['sha256']
            expected = job['expected'].get(row['sha256'])
            if expected is not None:
                _require(all(row[k] == expected[k] for k in (*IDENTITY_FIELDS, 'bytes', 'manifest_sha256'))
                    and _dependencies(row) == _dependencies(expected), 'Public row differs from its frozen source context')
            for dep in _dependencies(row):
                _require(dep['sha256'] in job['required'] and _identity(public[dep['sha256']]) == dep,
                    'Dependency does not resolve by its exact byte identity inside the context')
        if job['root']:
            _require(_identity(public[job['root']['sha256']]) == job['root'], 'Canonical root identity changed')
            reached, todo = set(), [job['root']['sha256']]
            while todo:
                checksum = todo.pop()
                if checksum in reached:
                    continue
                reached.add(checksum)
                todo.extend(d['sha256'] for d in _dependencies(public[checksum]))
            _require(reached == job['required'], 'Canonical dependency closure differs from its frozen source map')
        profile = {'generated_by':GENERATED_BY, 'id':job['name'], 'kind':job['kind'],
            'original_context':job['original_context'], 'root':job['root'],
            'availability':'complete_verified_release_rows', 'dependency_selection':'exact_sha256',
            'new_runtime_qualification':False}
        if 'original_index_sha256' in job:
            profile['original_index_sha256'] = job['original_index_sha256']
        manifest = {'schema_version':1, 'kind':'compiler_playground_package_repository',
            'profile':profile, 'packages':sorted(rows, key=lambda row:(_key(row), row['sha256']))}
        content = _write_owned(destination, manifest)
        ready.append({'id':job['name'], 'kind':job['kind'], 'path':manifest_prefix + '/' + destination.name,
            'artifacts':len(rows), 'root':job['root'], **content})
    return {'schema_version':1, 'kind':'cpg_public_dependency_profile_summary',
        'published_artifact_count':len(public), 'ready_profiles':ready, 'pending_profiles':pending,
        'missing_sha256s':sorted({sha for row in pending for sha in row['missing_sha256s']})}
