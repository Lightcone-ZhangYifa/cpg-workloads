#!/usr/bin/env python3
"""Verify every installed payload entry against the archive-bound recipe lock."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def snapshot(root):
    result = []
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == '.cpg-prefix.json':
                continue
            info = path.lstat()
            row = {'path': relative, 'mode': stat.S_IMODE(info.st_mode) & 0o777}
            if stat.S_ISREG(info.st_mode):
                row.update(kind='file', bytes=info.st_size, sha256=digest(path))
            elif stat.S_ISDIR(info.st_mode):
                row.update(kind='directory')
            elif stat.S_ISLNK(info.st_mode):
                if not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError('payload symlink escapes prefix: ' + relative)
                row.update(kind='symlink', target=os.readlink(path))
            else:
                raise ValueError('unsupported payload entry: ' + relative)
            result.append(row)
        directories[:] = sorted(x for x in directories
            if not (Path(directory) / x).is_symlink())
    return sorted(result, key=lambda row: row['path'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args, extra = parser.parse_known_args()
    prefix = args.prefix.absolute()
    if prefix.is_symlink() or not prefix.is_dir():
        raise ValueError('prefix must be an ordinary installed directory')
    root = Path(__file__).resolve().parent
    expected = json.loads((root / 'payload-inventory.json').read_text())
    actual = snapshot(prefix)
    if actual != expected:
        old = {x['path']: x for x in expected}
        new = {x['path']: x for x in actual}
        changed = [p for p in sorted(old.keys() | new.keys()) if old.get(p) != new.get(p)]
        print('CPG_PAYLOAD_INTEGRITY_REJECTED ' + json.dumps(changed[:20]), file=sys.stderr)
        return 65
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    run = subprocess.run([sys.executable, '-B', str(root / 'resource_check.py'),
        '--prefix', str(prefix), '--output', str(args.output), *extra], env=env)
    if run.returncode:
        return run.returncode
    result = json.loads((args.output / 'result.json').read_text())
    if result.get('status') != 'passed':
        raise ValueError('resource check exited zero without a passed result')
    if snapshot(prefix) != expected:
        raise ValueError('resource check modified its installed payload')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
