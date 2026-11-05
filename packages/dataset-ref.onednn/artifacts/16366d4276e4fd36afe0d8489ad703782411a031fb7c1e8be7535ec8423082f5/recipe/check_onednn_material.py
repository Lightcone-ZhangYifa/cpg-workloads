#!/usr/bin/env python3
"""Check the delivered oneDNN source tree identity without compiling or running it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat

COMMIT = '78a459b122000e7bb979a1f7802b51492eea2dc4'
TREE = 'c96b3bf710593942efea23a635344bac9e8b2437'
FILES = 5488
BYTES = 94026130


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    root = args.prefix / 'dataset-research' / 'onednn'
    if root.is_symlink() or not root.is_dir():
        raise ValueError('The delivered oneDNN material directory is missing')
    count = 0
    total = 0

    def tree_hash(directory: Path) -> bytes:
        nonlocal count, total
        entries = []
        for child in directory.iterdir():
            info = child.lstat()
            name = child.name.encode('utf-8')
            if stat.S_ISLNK(info.st_mode):
                raise ValueError('The original oneDNN tree has no symbolic links')
            if stat.S_ISDIR(info.st_mode):
                mode, oid, key = b'40000', tree_hash(child), name + b'/'
            elif stat.S_ISREG(info.st_mode):
                count += 1
                total += info.st_size
                if count > FILES or total > BYTES:
                    raise ValueError('The material exceeds its recorded source inventory')
                digest = hashlib.sha1(b'blob ' + str(info.st_size).encode() + b'\0')
                read = 0
                with child.open('rb') as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
                        read += len(block)
                if read != info.st_size:
                    raise ValueError('A material file changed during its read check')
                mode = b'100755' if info.st_mode & 0o111 else b'100644'
                oid, key = digest.digest(), name
            else:
                raise ValueError('The original tree contains only files and directories')
            entries.append((key, mode + b' ' + name + b'\0' + oid))
        data = b''.join(value for _, value in sorted(entries))
        return hashlib.sha1(b'tree ' + str(len(data)).encode() + b'\0' + data).digest()

    actual = tree_hash(root).hex()
    if (actual, count, total) != (TREE, FILES, BYTES):
        raise ValueError('The source tree differs from its recorded Git identity')
    print(json.dumps({'status': 'passed', 'scope': 'material readability and Git tree identity',
                      'source_commit': COMMIT, 'git_tree': actual,
                      'files': count, 'bytes': total, 'native_execution': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
