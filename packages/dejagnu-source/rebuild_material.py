#!/usr/bin/env python3
"""Recreate the frozen DejaGNU material with official CPG pack and local inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from compiler_playground.packages import pack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    spec = json.loads((root / 'package.json').read_text())
    provenance = json.loads((root / 'packaging-provenance.json').read_text())
    expected = json.loads((root / 'artifact-lock.json').read_text())
    manifest = json.loads((root / 'artifacts' / expected['sha256'] / 'manifest.json').read_text())
    source = spec['sources'][0]
    if not args.archive.is_file() or args.archive.stat().st_size != source['bytes']:
        raise ValueError('Provide the exact locked upstream source archive')
    with args.archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != source['sha256']:
            raise ValueError('Upstream archive SHA-256 differs from the source lock')
    with tempfile.TemporaryDirectory(prefix='dejagnu-material-') as temporary:
        payload = Path(temporary) / 'payload'
        shutil.copytree(root / 'source/dejagnu-1.6.3', payload / 'sources/dejagnu')
        copies = [(args.archive, 'original-inputs/dejagnu-1.6.3.tar.gz'),
                  (root / 'README.md', 'share/cpg-material/README.md'),
                  (root / 'LICENSE.CPG', 'share/licenses/LICENSE.CPG')]
        for source_file, relative in copies:
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target)
        for row in manifest['files']:
            if row['path'] == 'payload' or row['path'].startswith('payload/'):
                target = Path(temporary) / row['path']
                if row['kind'] == 'directory':
                    target.mkdir(parents=True, exist_ok=True)
                target.chmod(row['mode'])
        result = pack(spec, args.output, method='material', payload=payload,
                      recipe_dir=root / 'recipe', provenance=provenance)
    if any(result[key] != expected[key] for key in ('sha256', 'bytes', 'manifest_sha256')):
        raise ValueError('Recreated archive differs from the frozen artifact identity')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
