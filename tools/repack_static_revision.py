#!/usr/bin/env python3
"""Repack reviewed metadata/check revisions; never build or execute a workload."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile


def _require(value, message):
    if not value:
        raise ValueError(message)


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _relative(value):
    p = PurePosixPath(value)
    _require(value and not p.is_absolute() and '..' not in p.parts and '\\' not in value
        and p.as_posix() == value, 'Unsafe revision member path')
    return p


def output_identity_mode(revision):
    """Only an explicit reviewed-manifest mode may omit the final archive lock."""
    mode = revision.get('output_identity', 'exact')
    _require(mode in ('exact', 'derive-from-reviewed-manifest'), 'Unknown revision output identity mode')
    if mode == 'derive-from-reviewed-manifest':
        original_manifest = revision.get('original_artifact', {}).get('manifest_sha256')
        _require(isinstance(original_manifest, str) and re.fullmatch(r'[0-9a-f]{64}', original_manifest),
            'Derived output requires the exact original manifest fingerprint')
        corrected = revision.get('corrected', {})
        _require(corrected.get('sha256') is None and corrected.get('bytes') is None,
            'Derived output must not pretend to have a precomputed archive identity')
    return mode


def repack(original, template, revision, output):
    """Use verified original payload plus exact reviewed authored files and notices."""
    from compiler_playground.packages import pack, verify_package
    from compiler_playground.packages.spec import digest, validate_spec

    derived = output_identity_mode(revision) == 'derive-from-reviewed-manifest'
    original, template, output = Path(original), Path(template), Path(output)
    _require(original.is_file() and not original.is_symlink(), 'Missing ordinary original archive')
    _require(_sha(original) == revision['original_artifact']['sha256']
        and original.stat().st_size == revision['original_artifact']['bytes'], 'Incorrect original archive identity')
    manifest = json.loads((template / 'manifest.json').read_text())
    _require(digest({k:v for k,v in manifest.items() if k != 'manifest_sha256'}) == manifest['manifest_sha256']
        == revision['corrected']['manifest_sha256'], 'Reviewed manifest changed')
    if derived:
        _require(digest(manifest['files']) == manifest['inventory_sha256'], 'Reviewed inventory fingerprint changed')
    spec = validate_spec(manifest['package'])
    _require(json.loads((template / 'package.json').read_text()) == spec, 'Reviewed package definition changed')
    _require(not output.exists() and not output.is_symlink(), 'Output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cpg-static-revision-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        normalized = temporary / 'verified-metadata.archive'
        # Replace only the manifest package definition in an intermediate copy.
        # This lets the normal verifier check all original payload bytes even
        # when the original check declarations were structurally malformed.
        with tarfile.open(original, 'r:gz') as archive:
            rows = archive.getmembers()
            _require(len({r.name for r in rows}) == len(rows), 'Duplicate original archive member')
            old = json.load(archive.extractfile('manifest.json'))
            _require(digest({k:v for k,v in old.items() if k != 'manifest_sha256'}) == old['manifest_sha256'],
                'Original manifest fingerprint differs')
            if revision['original_artifact'].get('manifest_sha256') is not None:
                _require(old['manifest_sha256'] == revision['original_artifact']['manifest_sha256'],
                    'Original manifest differs from the reviewed revision lock')
            for key in ('id', 'version', 'provider', 'target', 'dependencies', 'sources'):
                _require(old['package'][key] == spec[key], 'Revision changes original package identity/lock: ' + key)
            for key in ('method', 'prefix_policy', 'resolved_dependencies', 'resolved_sources', 'sources'):
                if key == 'resolved_dependencies' and old.get(key) != manifest.get(key):
                    retained = spec['metadata'].get('extension_integration_requirements', {}).get('historical_dependency_evidence')
                    _require(revision.get('dependency_evidence_reclassification') == old.get(key) == retained
                        and manifest.get(key) == [] and all(not v for v in spec['dependencies'].values()),
                        'Historical dependency evidence was not preserved exactly')
                else:
                    _require(old.get(key) == manifest.get(key), 'Revision changes installation identity/lock: ' + key)
            checked = copy.deepcopy(old)
            checked['package'] = spec
            checked['resolved_dependencies'] = manifest['resolved_dependencies']
            checked['manifest_sha256'] = digest({k:v for k,v in checked.items() if k != 'manifest_sha256'})
            raw = (json.dumps(checked, indent=2, sort_keys=True) + '\n').encode()
            with normalized.open('xb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as target:
                    for row in rows:
                        _relative(row.name)
                        info = copy.copy(row)
                        if row.name == 'manifest.json':
                            info.size = len(raw)
                            target.addfile(info, io.BytesIO(raw))
                        else:
                            source = archive.extractfile(row) if row.isfile() else None
                            target.addfile(info, source)
                            if source is not None:
                                source.close()
        root = temporary / 'original'
        verify_package(normalized, extract=root)
        for directory in ('recipe', 'tools'):
            path = root / directory
            if path.exists():
                shutil.rmtree(path)
        authored = [r for r in manifest['files'] if r['path'].split('/')[0] in ('recipe', 'tools')]
        for row in authored:
            relative = _relative(row['path'])
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if row['kind'] == 'directory':
                target.mkdir(exist_ok=True)
            elif row['kind'] == 'file':
                source = template / relative
                _require(source.is_file() and not source.is_symlink() and _sha(source) == row['sha256']
                    and source.stat().st_size == row['bytes'], 'Reviewed authored file changed')
                shutil.copyfile(source, target)
            elif row['kind'] == 'symlink':
                raise ValueError('Static metadata revisions require ordinary authored files')
            else:
                raise ValueError('Unsupported authored file kind')
            if row['kind'] != 'symlink':
                target.chmod(row['mode'])
        before = {r['path']:r for r in old['files'] if r['path'].split('/')[0] in ('payload', 'sources')}
        after = {r['path']:r for r in manifest['files'] if r['path'].split('/')[0] in ('payload', 'sources')}
        _require(all(after.get(name) == row for name,row in before.items()), 'Revision changes original payload bytes/modes')
        additions = {r['path']:r for r in revision.get('added_notice_files', [])}
        for name,row in after.items():
            if name in before:
                continue
            _require(name in ('payload/share', 'payload/share/licenses') or name.startswith('payload/share/licenses/'), 'Unexpected new payload member')
            target = root / _relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if row['kind'] == 'directory':
                target.mkdir(exist_ok=True)
            else:
                _require(row['kind'] == 'file' and name in additions, 'Undeclared added notice')
                source = template / _relative(additions[name]['template_path'])
                _require(source.is_file() and not source.is_symlink() and _sha(source) == row['sha256']
                    and source.stat().st_size == row['bytes'], 'Reviewed notice identity differs')
                shutil.copyfile(source, target)
            target.chmod(row['mode'])
        result = pack(spec, output, method=manifest['method'],
            payload=root / 'payload' if manifest['method'] in ('binary', 'material') else None,
            sources={r['id']:root / r['path'] for r in manifest['sources']} if manifest['method'] == 'source' else None,
            recipe_dir=root / 'recipe' if (root / 'recipe').is_dir() else None,
            tools_dir=root / 'tools' if (root / 'tools').is_dir() else None,
            prefix=manifest['prefix_policy']['prefix'], relocatable=manifest['prefix_policy']['kind'] == 'relocatable',
            provenance=manifest['provenance'], resolved_dependencies=manifest['resolved_dependencies'],
            resolved_sources=manifest.get('resolved_sources'))
        if not derived and (result['sha256'] != revision['corrected']['sha256'] or result['bytes'] != revision['corrected']['bytes']):
            output.unlink(missing_ok=True)
            raise ValueError('Static repack differs from the reviewed corrected artifact identity')
        verified = verify_package(output, expected_sha256=result['sha256'], expected_bytes=result['bytes'])
        if derived and verified['manifest'] != manifest:
            output.unlink(missing_ok=True)
            raise ValueError('Derived archive manifest differs from the complete reviewed manifest')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--revision', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--framework', type=Path)
    args = parser.parse_args()
    if args.framework:
        sys.path.insert(0, str(args.framework))
    result = repack(args.original, args.template, json.loads(args.revision.read_text()), args.output)
    print(json.dumps({'path':str(result), 'sha256':_sha(result), 'bytes':result.stat().st_size,
        'build_executed':False, 'functional_tests_executed':False}))
