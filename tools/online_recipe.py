#!/usr/bin/env python3
"""Static import and exact repacking of modern payload-free online recipes.

Reading this module never acquires inputs, builds software, or executes recipes.
Legacy manifest/acquire.py archives dispatch to the sibling legacy_online module.
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

FORMATS = {
    'cpg_online_material_recipe',
    'cpg_online_source_recipe',
    'cpg_online_binary_recipe',
}
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_FILES = 4096
SHA = re.compile(r'[0-9a-f]{64}\Z')
IDENTIFIER = re.compile(r'[a-z0-9][a-z0-9.+_-]*\Z')


def _require(value, message):
    if not value:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            _require(key not in out, 'Duplicate JSON key: ' + key)
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=unique)


def _relative(name):
    _require(isinstance(name, str) and name and name != '.', 'Empty recipe path')
    p = PurePosixPath(name)
    _require(not p.is_absolute() and '..' not in p.parts and '\\' not in name
        and p.as_posix() == name and not any(ord(c) < 32 for c in name),
        'Unsafe recipe path: ' + repr(name))
    _require(p.parts[0] not in {'payload', 'sources'}, 'Online recipe embeds a payload tree')
    return p


def _directory(path):
    p = Path(path).absolute()
    _require(not any(q.is_symlink() for q in [p, *p.parents]), 'Recipe directory traverses a symlink')
    return p


def _slug(value, limit):
    original = str(value)
    clean = re.sub(r'[^a-zA-Z0-9.+_-]+', '-', original).strip('-.') or 'unknown'
    if clean != original or len(clean) > limit:
        clean = clean[:limit - 13] + '-' + hashlib.sha256(original.encode()).hexdigest()[:12]
    return clean


def _asset_name(spec, checksum):
    values = [_slug(spec['id'], 60), _slug(spec['version'], 40),
        'recipe-v1-' + checksum[:12], 'online',
        _slug(spec['target']['os'] + '-' + spec['target']['arch'], 26), checksum[:20]]
    return 'cpg--' + '--'.join(values) + '.cpgrecipe.tar.gz'


def _validate_spec_shape(spec):
    """Check the immutable source declaration without importing the package manager."""
    _require(isinstance(spec, dict) and type(spec.get('schema_version')) is int
        and spec['schema_version'] == 1, 'Invalid package schema')
    _require(isinstance(spec.get('id'), str) and IDENTIFIER.fullmatch(spec['id']), 'Invalid package ID')
    for key in ('version', 'build', 'provider'):
        _require(isinstance(spec.get(key), str) and spec[key].strip() and '\0' not in spec[key],
            'Missing package ' + key)
    _require(spec['provider'] in {'apt', 'python', 'source', 'binary', 'material', 'component', 'meta', 'host'},
        'Invalid package provider')
    target = spec.get('target')
    _require(isinstance(target, dict) and all(isinstance(target.get(k), str) and target[k].strip()
        for k in ('os', 'arch', 'distribution', 'distribution_version')), 'Incomplete package target')
    dependencies = spec.get('dependencies')
    _require(isinstance(dependencies, dict) and set(dependencies) == {'build', 'run', 'system'},
        'Missing dependency phases')
    for names in dependencies.values():
        _require(isinstance(names, list) and all(isinstance(n, str) and IDENTIFIER.fullmatch(n) for n in names)
            and len(names) == len(set(names)), 'Invalid dependency list')
    for key in ('recipe', 'usage', 'metadata'):
        _require(isinstance(spec.get(key), dict), 'Missing package ' + key)
    _require(isinstance(spec['usage'].get('summary'), str) and spec['usage']['summary'].strip(),
        'Missing package usage summary')
    _require(isinstance(spec.get('checks'), list) and all(isinstance(c, dict) for c in spec['checks']),
        'Invalid package checks')
    sources = spec.get('sources')
    _require(isinstance(sources, list), 'Missing package sources')
    for source in sources:
        _require(isinstance(source, dict) and isinstance(source.get('id'), str)
            and IDENTIFIER.fullmatch(source['id']) and {'url', 'sha256', 'bytes', 'material_path'} <= set(source),
            'Incomplete source declaration')
        _require(source['sha256'] is None or isinstance(source['sha256'], str) and SHA.fullmatch(source['sha256']),
            'Invalid source digest')
        _require(source['bytes'] is None or type(source['bytes']) is int and source['bytes'] >= 0,
            'Invalid source byte count')
        _require(source['url'] is None or isinstance(source['url'], str) and source['url'].strip()
            and '\0' not in source['url'], 'Invalid source URL')
    catalog = spec['metadata'].get('catalog')
    if catalog is not None:
        _require(isinstance(catalog, dict) and catalog.get('id') == spec['id'] and catalog.get('version') == spec['version'],
            'Package identity differs from its catalog')
        _require(_digest(catalog) == spec['metadata'].get('catalog_sha256'), 'Catalog fingerprint differs')
    return spec


def _validate_contents(contents):
    _require({'online.json', 'offline-manifest.json', 'run.py'} <= set(contents),
        'Modern recipe lacks its descriptor, offline manifest, or entry point')
    descriptor = _json(contents['online.json'])
    _require(descriptor.get('kind') in FORMATS and descriptor.get('embedded_payload_bytes') == 0,
        'Unsupported modern online recipe contract')
    offline = _json(contents['offline-manifest.json'])
    _require(offline.get('kind') == 'compiler_playground_resource_package'
        and offline.get('schema_version') == 1 and offline.get('method') in {'source', 'binary', 'material', 'wrapper'},
        'Invalid offline package manifest')
    spec = _validate_spec_shape(offline['package'])
    _require(IDENTIFIER.fullmatch(spec['id']) and spec['id'] == descriptor['resource_id'],
        'Online and offline package identities differ')
    _require(_digest({k:v for k,v in offline.items() if k != 'manifest_sha256'})
        == offline.get('manifest_sha256') == descriptor['offline_artifact']['manifest_sha256'],
        'Offline manifest identity differs from the recipe')
    artifact = descriptor['offline_artifact']
    _require(_digest(offline['files']) == offline.get('inventory_sha256'), 'Offline inventory fingerprint differs')
    _require(artifact.get('method') == offline['method'], 'Offline installation method differs')
    _require(isinstance(artifact.get('sha256'), str) and SHA.fullmatch(artifact['sha256'])
        and type(artifact.get('bytes')) is int and artifact['bytes'] > 0,
        'Missing expected offline artifact identity')
    rows = descriptor.get('recipe_files')
    _require(isinstance(rows, list), 'Missing authored recipe inventory')
    expected = {}
    for row in rows:
        name = _relative(row['path']).as_posix()
        _require(name != 'online.json' and name not in expected, 'Duplicate authored recipe inventory path')
        _require(isinstance(row.get('sha256'), str) and SHA.fullmatch(row['sha256'])
            and type(row.get('bytes')) is int and row['bytes'] >= 0, 'Incomplete authored file identity')
        expected[name] = row
    _require(set(contents) == set(expected) | {'online.json'}, 'Missing or undeclared authored recipe file')
    for name, row in expected.items():
        _require(len(contents[name]) == row['bytes'] and hashlib.sha256(contents[name]).hexdigest() == row['sha256'],
            'Authored recipe file changed: ' + name)
    original = descriptor.get('original_source_locks')
    _require(isinstance(original, list) and original, 'Missing original source declarations')
    _require(original == spec['sources'], 'Online source declarations differ from the offline package')
    effective = {s['id']: s for s in original}
    _require(len(effective) == len(original), 'Duplicate source declaration')
    for lock in descriptor.get('resolved_acquisition_locks', []):
        base = effective.get(lock['id'])
        _require(base is not None and all(value == lock.get(key) for key, value in base.items()
            if not (key in {'sha256', 'bytes'} and value is None)), 'Acquisition extension changes a fixed source field')
        effective[lock['id']] = lock
    _require(all(isinstance(s.get('sha256'), str) and SHA.fullmatch(s['sha256'])
        and type(s.get('bytes')) is int and s['bytes'] >= 0 for s in effective.values()),
        'Effective acquisition byte locks are incomplete')
    for name, data in contents.items():
        if name.endswith('.py'):
            ast.parse(data.decode('utf-8'), filename=name)
    return descriptor, spec


def _read_archive(path):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink(), 'Recipe archive is not an ordinary file')
    contents, members, total = {}, [], 0
    with tarfile.open(path, 'r:gz') as archive:
        for m in archive:
            name = _relative(m.name).as_posix()
            _require(m.isfile() and not m.issparse(), 'Online recipes contain ordinary authored files only')
            _require(name not in contents and len(contents) < MAX_FILES, 'Duplicate or excessive recipe members')
            total += m.size
            _require(0 <= m.size <= MAX_EXPANDED_BYTES and total <= MAX_EXPANDED_BYTES,
                'Online recipe exceeds the authored-metadata size limit')
            _require(0 <= m.mode <= 0o777, 'Invalid ordinary recipe mode')
            data = archive.extractfile(m).read(m.size + 1)
            _require(len(data) == m.size, 'Truncated authored recipe file')
            contents[name] = data
            members.append({'path':name, 'bytes':m.size, 'sha256':hashlib.sha256(data).hexdigest(),
                'mode':m.mode, 'type':m.type.decode('ascii'), 'uid':m.uid, 'gid':m.gid,
                'uname':m.uname, 'gname':m.gname, 'mtime':m.mtime, 'pax_headers':dict(m.pax_headers)})
    descriptor, spec = _validate_contents(contents)
    return contents, members, descriptor, spec


def _import_modern_recipe(path, root, origin=None):
    """Retain complete authored files and return a static review record."""
    path = Path(path)
    checksum, size = _sha(path), path.stat().st_size
    contents, members, descriptor, spec = _read_archive(path)
    _require(_sha(path) == checksum and path.stat().st_size == size, 'Recipe changed during inspection')
    root = _directory(root)
    destination = _directory(root / 'packages' / spec['id'] / 'online' / checksum)
    catalog = spec.get('metadata', {}).get('catalog', {})
    findings, warnings = [], []
    if not catalog.get('license_class') or not catalog.get('license_id'):
        findings.append('incomplete_license_metadata')
    if catalog.get('license_class') != 'open' or catalog.get('redistributable') is False:
        warnings.append('Referenced upstream material requires a separate redistribution review; this asset contains only authored preparation code and metadata, with zero embedded upstream payload bytes')
    record = {'id':spec['id'], 'version':spec['version'], 'build':'recipe-v1-' + checksum[:12],
        'target':spec['target'], 'provider':spec['provider'], 'method':'online-recipe',
        'sha256':checksum, 'bytes':size, 'template':destination.relative_to(root).as_posix(),
        'asset_name':_asset_name(spec, checksum), 'online_format':descriptor['kind'],
        'archive_members':members, 'structure':'passed', 'build_check':'not_run', 'functional':'not_run',
        'review_policy':'static-trust-v1', 'static_review':{'status':'passed' if not findings else 'needs_correction',
        'checks':['complete_authored_inventory', 'offline_manifest_identity', 'locked_source_acquisition',
        'python_template_syntax', 'license_metadata'], 'findings':findings, 'warnings':warnings,
        'build_executed':False, 'functional_tests_executed':False},
        'qualification_errors':findings, 'release_eligible':not findings,
        'qualification_scope':'Locked online preparation recipe; no acquisition, build, installation, or native execution observed',
        'source_build_or_runtime_qualified':False, 'origins':[origin] if origin else []}
    if destination.exists():
        verify_template(destination, record)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.online-import-', dir=destination.parent) as td:
            stage = Path(td) / 'template'
            stage.mkdir()
            for row in members:
                target = stage / _relative(row['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents[row['path']])
                target.chmod(row['mode'])
            os.replace(stage, destination)
    return record


def _verify_modern_template(template, record):
    """Read and verify exact authored bytes; never run recipe code."""
    template = _directory(template)
    _require(template.is_dir(), 'Missing online recipe template')
    rows = record['archive_members']
    expected = {r['path']:r for r in rows}
    _require(len(expected) == len(rows), 'Duplicate retained recipe member')
    contents = {}
    parents = {p.as_posix() for name in expected for p in PurePosixPath(name).parents if p != PurePosixPath('.')}
    for p in template.rglob('*'):
        _require(not p.is_symlink(), 'Unpacked online recipe contains a symlink')
        relative = p.relative_to(template).as_posix()
        if p.is_dir():
            _require(relative in parents, 'Undeclared recipe directory')
            continue
        _require(p.is_file() and relative in expected, 'Undeclared online recipe file')
        row = expected[relative]
        data = p.read_bytes()
        _require(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
            and p.stat().st_mode & 0o7777 == row['mode'], 'Retained online recipe identity differs: ' + relative)
        contents[relative] = data
    _require(set(contents) == set(expected), 'Retained online recipe files are missing')
    descriptor, spec = _validate_contents(contents)
    _require(all(record.get(k) == spec[k] for k in ('id', 'version', 'target')),
        'Retained online artifact identity differs')
    _require(record.get('online_format') == descriptor['kind']
        and record.get('asset_name') == _asset_name(spec, record['sha256']), 'Online artifact format or name differs')
    return descriptor


def _repack_modern(template, record, output):
    """Reproduce original tar headers; require exact bytes or original pass-through."""
    template, output = Path(template), Path(output)
    verify_template(template, record)
    _require(not output.exists() and not output.is_symlink(), 'Repack output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open('xb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for row in record['archive_members']:
                    info = tarfile.TarInfo(row['path'])
                    for key in ('mode', 'uid', 'gid', 'uname', 'gname', 'mtime', 'pax_headers'):
                        setattr(info, key, row[key])
                    info.type = row['type'].encode('ascii')
                    info.size = row['bytes']
                    with (template / _relative(row['path'])).open('rb') as source:
                        archive.addfile(info, source)
        if output.stat().st_size != record['bytes'] or _sha(output) != record['sha256']:
            raise ValueError('Original archive envelope does not reproduce exactly; use the verified original archive pass-through')
    except BaseException:
        if output.is_file():
            output.unlink()
        raise
    return output


def _legacy_module():
    import importlib
    return importlib.import_module('legacy_online')


def _archive_format(path):
    total = 0
    with tarfile.open(path, 'r:gz') as archive:
        for count, member in enumerate(archive):
            _relative(member.name)
            total += member.size
            _require(count < MAX_FILES and 0 <= member.size <= MAX_EXPANDED_BYTES
                and total <= MAX_EXPANDED_BYTES, 'Online recipe exceeds metadata limits')
            if member.name in {'online.json', 'manifest.json'} and member.isfile():
                descriptor = _json(archive.extractfile(member).read(member.size + 1))
                value = descriptor.get('kind') if member.name == 'online.json' else descriptor.get('format')
                if value in FORMATS or value == 'compiler-playground-original-material-online-recipe-v1':
                    return value
    raise ValueError('Unrecognized online recipe format')


def _verify_legacy_template(template, record):
    legacy = _legacy_module()
    descriptor = legacy.verify_template(template, record)
    identity = legacy.artifact_identity(descriptor, record['sha256'])
    _require(all(record.get(k) == v for k, v in identity.items()), 'Legacy online artifact identity differs')
    _require(record.get('asset_name') == legacy.artifact_name(descriptor, record['sha256']),
        'Legacy online artifact name differs')
    for row in record['archive_members']:
        name = _relative(row['path']).as_posix()
        if name.endswith('.py'):
            ast.parse((Path(template) / name).read_text(), filename=name)
    return descriptor


def import_recipe(path, root, origin=None):
    """Import either supported format; the standard-library path executes no recipe."""
    if _archive_format(path) in FORMATS:
        return _import_modern_recipe(path, root, origin)
    record = _legacy_module().import_recipe(path, root, origin)
    descriptor = _verify_legacy_template(Path(root) / record['template'], record)
    record.update(provider=descriptor.get('original_provider', 'material'), review_policy='static-trust-v1',
        release_eligible=True, qualification_errors=[], build_check='not_run', functional='not_run',
        qualification_scope='Locked original-source acquisition recipe; no acquisition, build, installation, or native execution observed',
        static_review={'status':'passed', 'checks':['complete_authored_inventory', 'locked_source_acquisition',
        'python_template_syntax', 'zero_embedded_payload'], 'findings':[],
        'warnings':['This authored acquisition recipe does not redistribute the referenced upstream material; its upstream catalog/notice reference is preserved and acquisition does not grant redistribution permission'],
        'build_executed':False, 'functional_tests_executed':False})
    return record


def verify_template(template, record):
    if record.get('online_format') in FORMATS:
        return _verify_modern_template(template, record)
    _require(record.get('online_format') == 'compiler-playground-original-material-online-recipe-v1',
        'Unsupported online recipe record format')
    return _verify_legacy_template(template, record)


def repack(template, record, output):
    """Return an exact archive path for either format, or require original pass-through."""
    if record.get('online_format') in FORMATS:
        return _repack_modern(template, record, output)
    verify_template(template, record)
    output = Path(output)
    _require(not output.exists() and not output.is_symlink(), 'Repack output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.online-repack-', dir=output.parent) as temporary:
        result = _legacy_module().repack(template, record, temporary, require_original=True)
        os.replace(result['path'], output)
    return output
