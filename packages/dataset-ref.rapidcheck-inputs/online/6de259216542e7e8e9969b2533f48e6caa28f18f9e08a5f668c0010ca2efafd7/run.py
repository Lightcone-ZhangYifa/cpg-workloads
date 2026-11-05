#!/usr/bin/env python3
"""Prepare an exact source CPG using existing acquisition and package APIs.

This controller does not install or compile a resource. A successful cached
replay is not evidence that a live origin URL was fetched in this run.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def need(value, message):
    if not value:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare'])
    parser.add_argument('--descriptor', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--framework-path', type=Path)
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    if args.framework_path:
        sys.path.insert(0, str(args.framework_path / 'src'))
    sys.dont_write_bytecode = True
    from compiler_playground.resource_deploy import acquire_file
    from compiler_playground.packages import pack, verify_package
    from compiler_playground.packages.archive import inventory, resolved_source_locks
    descriptor = json.loads(args.descriptor.read_text())
    root = args.descriptor.resolve().parent
    need(descriptor['kind'] == 'cpg_exact_native_source_replay', 'Unexpected controller descriptor')
    template_path = root / descriptor['source_manifest']['path']
    need(sha(template_path) == descriptor['source_manifest']['sha256'], 'Source manifest template changed')
    template = json.loads(template_path.read_text())
    spec = template['package']
    need(template['method'] == 'source', 'Controller only prepares source packages')
    need(spec['id'] == descriptor['resource_id'], 'Resource identity differs')
    expected_recipe = [{**row, 'path': row['path'][7:]} for row in template['files'] if row['path'].startswith('recipe/')]
    need(inventory(root / 'recipe') == expected_recipe, 'The selected active recipe differs from the source artifact')
    locks = resolved_source_locks(spec, template.get('resolved_sources'))
    acquisition = []
    sources = {}
    with tempfile.TemporaryDirectory(prefix='cpg-exact-native-source-prepare-') as tmp:
        tools = None
        for lock in locks:
            item = {'id': lock['id'], 'source_url': lock['url'], 'sha256': lock['sha256'],
                    'archive_bytes': lock['bytes'], 'license_class': spec['metadata']['catalog']['license_class']}
            if args.no_network:
                item['bundled_path'] = str(args.cache.resolve() / 'sha256' / lock['sha256'][:2] / lock['sha256'])
            receipt = {}
            sources[lock['id']] = acquire_file(item, args.cache, receipt=receipt)
            acquisition.append({'scope': 'original_canonical_source', 'lock': lock, 'receipt': receipt})
        tool_rows = [row for row in template['files'] if row['path'] == 'tools' or row['path'].startswith('tools/')]
        if tool_rows:
            tool_lock_name = spec['recipe'].get('artifact_only_source_tools_lock')
            need(isinstance(tool_lock_name, str) and '/' not in tool_lock_name and tool_lock_name.endswith('.json'), 'Missing explicit artifact-only source tools lock')
            tool_lock = root / 'recipe' / tool_lock_name
            need(tool_lock.is_file(), 'Supplemental tools lack an explicit fixed Gitlink lock')
            bound = json.loads(tool_lock.read_text())
            tools = Path(tmp) / 'tools'; tools.mkdir(); tools.chmod(bound['tools_root_mode'])
            for lock in bound['artifacts']:
                relative = PurePosixPath(lock['path'])
                need(not relative.is_absolute() and '..' not in relative.parts and relative.as_posix() == lock['path'], 'Unsafe supplemental input path')
                item = {'id': lock['input_id'], 'source_url': lock['url'], 'sha256': lock['sha256'],
                        'archive_bytes': lock['bytes'], 'license_class': 'open'}
                if args.no_network:
                    item['bundled_path'] = str(args.cache.resolve() / 'sha256' / lock['sha256'][:2] / lock['sha256'])
                receipt = {}
                raw = acquire_file(item, args.cache, receipt=receipt)
                target = tools / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(raw, target); target.chmod(lock['mode'])
                acquisition.append({'scope': 'explicit_source_artifact_or_build_only_raw_input', 'lock': lock, 'receipt': receipt})
            for row in bound['directories']:
                target = tools / row['path']; target.mkdir(parents=True, exist_ok=True); target.chmod(row['mode'])
            expected_tools = [{**row, 'path': row['path'][6:]} for row in tool_rows if row['path'].startswith('tools/')]
            need(inventory(tools) == expected_tools, 'Artifact-only tools differ from the exact source manifest')
        artifact = pack(spec, args.output, method='source', sources=sources, recipe_dir=root / 'recipe',
                        tools_dir=tools, resolved_sources=template.get('resolved_sources'),
                        resolved_dependencies=template['resolved_dependencies'], provenance=template['provenance'])
        checked = verify_package(artifact['path'], expected_sha256=descriptor['artifact']['sha256'],
                                 expected_bytes=descriptor['artifact']['bytes'])
        need(checked['manifest'] == template, 'Prepared source manifest differs from the exact original template')
    result = {'status': 'passed', 'recorded_utc': datetime.now(timezone.utc).isoformat(),
              'resource_id': spec['id'], 'artifact': artifact, 'acquisition': acquisition,
              'network_requested': not args.no_network, 'no_network_mode': args.no_network,
              'qualification_scope': 'Exact raw-input acquisition and byte-identical source package preparation only; no new installation, compilation, functional, Dataset, OCI or hardware qualification.'}
    receipt_path = args.output.with_name(args.output.name + '.preparation.json')
    receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
