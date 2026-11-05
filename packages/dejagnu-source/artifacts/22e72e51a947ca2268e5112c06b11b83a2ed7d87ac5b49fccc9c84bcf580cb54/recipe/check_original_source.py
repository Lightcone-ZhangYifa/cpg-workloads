#!/usr/bin/env python3
"""Verify the complete locked DejaGNU source material without running it."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    source = args.prefix / 'upstream-original' / 'dejagnu-1.6.3.tar.gz'
    if not source.is_file() or source.is_symlink():
        raise ValueError('The installed original source archive is missing or is a symlink')
    if source.stat().st_size != 622059:
        raise ValueError('Original source byte count differs from its lock')
    with source.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    if checksum != '87daefacd7958b4a69f88c6856dbd1634261963c414079d0c371f589cd66a2e3':
        raise ValueError('Original source SHA-256 differs from its lock')
    expected = {
        'dejagnu-1.6.3/runtest.exp',
        'dejagnu-1.6.3/lib/framework.exp',
        'dejagnu-1.6.3/COPYING',
        'dejagnu-1.6.3/README',
    }
    with tarfile.open(source, 'r:gz') as archive:
        rows = archive.getmembers()
        names = {row.name for row in rows}
        if len(rows) != 216 or len(names) != len(rows) or not expected <= names:
            raise ValueError('Original source archive inventory differs')
        for row in rows:
            path = PurePosixPath(row.name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unexpected source archive member path')
        for name in expected:
            row = archive.getmember(name)
            if not row.isfile() or row.size <= 0:
                raise ValueError('Required source or notice is not a readable ordinary file')
            with archive.extractfile(row) as stream:
                if len(stream.read(row.size + 1)) != row.size:
                    raise ValueError('Required source or notice is truncated')
    print(json.dumps({'status': 'passed', 'scope': 'complete-original-source-availability',
        'source_sha256': checksum, 'members': len(rows), 'software_execution': False}, sort_keys=True))


if __name__ == '__main__':
    main()
