"""Verify the retained exact-subtree material contract without running a package."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

def _path(value):
    if not isinstance(value, str) or not value or value == '.':
        raise ValueError('Empty source path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or p.as_posix() != value or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Unsafe source path')
    return p

def reviewed_subtree_material(manifest, template):
    """Return the original declared scope only when all immutable file locks agree.

    The caller already verifies original archive bytes and every payload hash.
    A monorepo archive remains unresolved; this contract covers the expressly
    declared Git subtree and its original root license, never source rebuilding.
    """
    try:
        spec = manifest['package']; recipe = spec['recipe']; provenance = manifest['provenance']
        if manifest['method'] != 'material' or recipe.get('monorepo_not_acquired') is not True:
            return None
        commit = recipe['source_commit']
        if not re.fullmatch('[0-9a-f]{40}', commit) or provenance['source_commit'] != commit:
            return None
        sources = spec['sources']
        if len(sources) != 1:
            return None
        source = sources[0]; url = urlsplit(source['url']); parts = url.path.strip('/').split('/')
        if (url.scheme != 'https' or url.netloc != 'codeload.github.com' or url.query or url.fragment
                or len(parts) != 4 or parts[2:] != ['tar.gz', commit] or source['id'] != spec['id']):
            return None
        repo = '/'.join(parts[:2])
        rows = {row['path']: row for row in manifest['files']}
        root = Path(template).resolve()
        def retained_json(name):
            row = rows[name]; path = root / _path(name)
            if row['kind'] != 'file' or not path.resolve().is_relative_to(root):
                raise ValueError('Unbound authored lock')
            data = path.read_bytes()
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Changed authored lock')
            return json.loads(data)
        locks = retained_json('recipe/source-subtree-locks.json')
        audit = retained_json('recipe/source-closure-audit.json')
        if (provenance['source_subtree_locks_sha256'] != rows['recipe/source-subtree-locks.json']['sha256']
                or recipe['source_closure_audit_sha256'] != rows['recipe/source-closure-audit.json']['sha256']
                or locks.get('monorepo_not_acquired') is not True
                or locks.get('canonical_monorepo_archive_sha256_and_bytes_remain_unresolved') is not True
                or locks['preserved_definition_fields']['sources'] != sources
                or audit['canonical_sources_preserved'] != sources
                or audit['source_commit'] != commit or audit.get('monorepo_not_acquired') is not True):
            return None
        scope = locks['declared_subtree_scope']
        if (not isinstance(scope, str) or not scope
                or scope not in spec['metadata']['catalog']['qualification_gaps']
                or recipe.get('original_declared_scope') != scope):
            return None
        definition = locks['formal_v02111_dataset_source_spec']; material = definition['source_materials']
        if (definition['revision'] != commit or material['revision'] != commit
                or material.get('kind') != 'exact_git_subtree_and_original_root_license'
                or material.get('full_monorepo_claimed') is not False):
            return None
        subtree = _path(material['subtree']).as_posix(); license_path = _path(definition['license_file']).as_posix()
        files = material['files']; paths = [row['path'] for row in files]
        if len(files) < 2 or len(set(paths)) != len(paths) or license_path not in paths:
            return None
        compact = lambda entries: {x['path']: (x['sha256'], x['bytes']) for x in entries}
        if compact(files) != compact(definition['files']) or compact(files) != compact(audit['source_files']):
            return None
        expected_paths = {'payload'}; tree_entries = []; total = 0
        for row in files:
            relative = _path(row['path']); path = relative.as_posix()
            if path != license_path and not path.startswith(subtree + '/'):
                return None
            if (row['url'] != 'https://raw.githubusercontent.com/' + repo + '/' + commit + '/' + path
                    or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                    or not re.fullmatch('[0-9a-f]{40}', row['git_blob_sha1'])
                    or type(row['bytes']) is not int or row['bytes'] < 0 or row['mode'] not in {0o644, 0o755}):
                return None
            name = 'payload/' + path; payload = rows[name]
            if payload['kind'] != 'file' or any(payload[key] != row[key] for key in ['sha256', 'bytes', 'mode']):
                return None
            expected_paths.add(name)
            expected_paths.update(parent.as_posix() for parent in PurePosixPath(name).parents if parent.as_posix() != '.')
            total += row['bytes']
            if path.startswith(subtree + '/'):
                leaf = path[len(subtree) + 1:]
                if '/' in leaf:
                    return None  # The retained format explicitly describes one flat subtree.
                mode = b'100755' if row['mode'] == 0o755 else b'100644'
                tree_entries.append((leaf.encode(), mode + b' ' + leaf.encode() + b'\0' + bytes.fromhex(row['git_blob_sha1'])))
        actual_payload = {path for path in rows if path == 'payload' or path.startswith('payload/')}
        if actual_payload != expected_paths or not tree_entries or total != audit['complete_material_bytes']:
            return None
        for path in expected_paths - {'payload/' + name for name in paths}:
            if rows[path]['kind'] != 'directory':
                return None
        tree = b''.join(entry for _, entry in sorted(tree_entries))
        tree_sha1 = hashlib.sha1(b'tree ' + str(len(tree)).encode() + b'\0' + tree).hexdigest()
        if (tree_sha1 != material['subtree_git_tree_sha1'] or tree_sha1 != recipe['subtree_git_tree_sha1']
                or tree_sha1 != audit['independently_recomputed_complete_subtree_sha1']):
            return None
        return {'source_commit': commit, 'subtree': subtree, 'subtree_git_tree_sha1': tree_sha1,
                'files': len(files), 'bytes': total, 'root_license': license_path,
                'full_monorepo_acquired': False, 'whole_archive_lock': 'unresolved_and_not_required_for_declared_subtree_material'}
    except (KeyError, TypeError, ValueError, OSError, UnicodeError):
        return None
