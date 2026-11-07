#!/usr/bin/env python3
"""Protected CPG check hook: verify every installed member, then run a fresh test."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time


def inventory(root):
    rows = []
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted([*directories, *files]):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == '.cpg-prefix.json':
                continue
            info = path.lstat()
            row = {'path': relative, 'mode': stat.S_IMODE(info.st_mode) & 0o777}
            if stat.S_ISREG(info.st_mode):
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                row.update(kind='file', bytes=info.st_size, sha256=digest)
            elif stat.S_ISDIR(info.st_mode):
                row.update(kind='directory')
            elif stat.S_ISLNK(info.st_mode):
                if not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError('Installed symlink escapes its prefix: ' + relative)
                row.update(kind='symlink', target=os.readlink(path))
            else:
                raise ValueError('Unexpected installed member type: ' + relative)
            rows.append(row)
        directories[:] = sorted(n for n in directories if not (Path(directory) / n).is_symlink())
    return sorted(rows, key=lambda row: row['path'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    prefix = args.prefix.resolve(strict=True)
    expected = json.loads((root / 'payload-inventory.json').read_text())
    actual = inventory(prefix)
    if actual != expected:
        known = {r['path']: r for r in expected}
        current = {r['path']: r for r in actual}
        changed = [p for p in sorted(set(known) | set(current)) if known.get(p) != current.get(p)]
        raise ValueError('CPG payload integrity mismatch before functional execution: ' + repr(changed[:20]))
    profile = json.loads((root / 'check-profile.json').read_text())
    args.build.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='cpg-functional-', dir=args.build))
    # Worker checks require a fresh absent directory and create it themselves.
    work.rmdir()
    def expand(text):
        text = text.replace('{prefix}', str(prefix)).replace('{work}', str(work))
        return re.sub(r'\{env:([A-Z][A-Z0-9_]*)\}', lambda m: os.environ[m[1]], text)
    argv = [expand(x) for x in profile['argv']]
    started = time.time()
    result = subprocess.run(argv, cwd=args.build, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), check=False)
    record = {'schema_version': 1, 'resource_id': profile['id'], 'argv': argv,
              'work': str(work), 'payload_integrity': 'verified',
              'returncode': result.returncode, 'elapsed_seconds': time.time() - started}
    (args.build / ('check-run-' + work.name + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    if result.returncode:
        raise SystemExit(result.returncode)
    if inventory(prefix) != expected:
        raise ValueError('Functional execution unexpectedly modified the installed payload')
    print('CPG_BOUNDED_FUNCTIONAL_PASS ' + profile['id'])


if __name__ == '__main__':
    main()
