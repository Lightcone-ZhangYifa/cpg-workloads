#!/usr/bin/env python3
"""Recreate the frozen Clang material with the official CPG package writer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from compiler_playground.packages import pack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    spec = json.loads((root / 'package.json').read_text())
    provenance = json.loads((root / 'packaging-provenance.json').read_text())
    expected = json.loads((root / 'artifact-lock.json').read_text())
    result = pack(spec, args.output, method='material', payload=root / 'payload',
                  recipe_dir=root / 'recipe', provenance=provenance)
    if any(result[key] != expected[key] for key in ('sha256', 'bytes', 'manifest_sha256')):
        raise ValueError('Recreated archive differs from its frozen artifact identity')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
