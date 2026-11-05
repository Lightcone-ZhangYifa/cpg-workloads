#!/usr/bin/env python3
"""Assemble verified original Intel PCM inputs without changing the main tree.

This helper creates a source tree only. It does not install dependencies, select
another source revision, grant a platform qualification, or modify a catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

# Source hooks may run under /usr/bin/python3 rather than the controller's
# virtual environment. Packaged recipes bind an unchanged, minimal copy of the
# existing framework I/O modules; no separate extraction/installation algorithm.
import sys
_RECIPE_DIRECTORY = Path(__file__).resolve().parent
if (_RECIPE_DIRECTORY / "_cpg_recipe_runtime").is_dir():
    sys.path.insert(0, str(_RECIPE_DIRECTORY))
    from _cpg_recipe_runtime.resource_deploy import (
        _publish_directory, relative_path, unpack_archive,
    )
    from _cpg_recipe_runtime.packages.archive import inventory
else:
    from compiler_playground.resource_deploy import (
        _publish_directory, relative_path, unpack_archive,
    )
    from compiler_playground.packages.archive import inventory


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reject_symlink_ancestors(path: Path) -> None:
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError(f'Path traverses a symbolic link: {parent}')


def assemble(main: Path, output: Path, recipe: Path) -> dict:
    main, output, recipe = (Path(p).absolute() for p in (main, output, recipe))
    for path in (main, output.parent, recipe):
        reject_symlink_ancestors(path)
    if not main.is_dir():
        raise ValueError('Main source must be an ordinary directory')
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if output == main or main in output.parents or output in main.parents:
        raise ValueError('Output and original source must not overlap')
    if output == recipe or recipe in output.parents or output in recipe.parents:
        raise ValueError('Output and recipe must not overlap')
    audit_file = recipe / 'supplements.json'
    if audit_file.is_symlink() or not audit_file.is_file():
        raise ValueError('Supplement lock must be an ordinary file')
    audit = json.loads(audit_file.read_text())
    before = inventory(main)
    if before != audit['original_main_inventory']:
        raise ValueError('Original main source contents differ')
    locks = audit['supplements']
    if not isinstance(locks, list) or not locks:
        raise ValueError('At least one exact supplemental input is required')
    mounts: list[Path] = []
    prepared = []
    for lock in locks:
        mount = Path(relative_path(lock['mount_path']))
        if mount.as_posix() != lock['mount_path'] or str(mount) == '.':
            raise ValueError('Non-canonical supplemental mount')
        if any(mount == old or mount in old.parents or old in mount.parents for old in mounts):
            raise ValueError('Overlapping supplemental mounts')
        mounts.append(mount)
        digest = lock['sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid supplemental SHA-256')
        if type(lock['bytes']) is not int or lock['bytes'] < 0 or type(lock['strip_root']) is not bool:
            raise ValueError('Invalid supplemental size or extraction mode')
        raw = recipe / 'inputs' / digest
        reject_symlink_ancestors(raw)
        if not raw.is_file() or raw.stat().st_size != lock['bytes'] or sha256(raw) != digest:
            raise ValueError('Supplement original identity mismatch: ' + lock['id'])
        destination = main / mount
        reject_symlink_ancestors(destination)
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError('Submodule mount is not an empty original placeholder')
        prepared.append((lock, raw, mount))
    output.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_ancestors(output.parent)
    with tempfile.TemporaryDirectory(prefix='.pcm-assemble-', dir=output.parent) as temp:
        tree = Path(temp) / 'tree'
        shutil.copytree(main, tree, symlinks=True)
        for lock, raw, mount in prepared:
            destination = tree / mount
            if destination.exists():
                destination.rmdir()
            unpack_archive(raw, destination, strip_root=lock['strip_root'])
        if inventory(main) != before:
            raise ValueError('Original main source changed during assembly')
        _publish_directory(tree, output)
    return {'status': 'assembled', 'supplements': len(locks),
            'original_main_unchanged': True, 'output': str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recipe', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    print(json.dumps(assemble(args.source, args.output, args.recipe), sort_keys=True))


if __name__ == '__main__':
    main()
