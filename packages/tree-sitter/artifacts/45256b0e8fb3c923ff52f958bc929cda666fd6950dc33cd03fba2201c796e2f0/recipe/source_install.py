#!/usr/bin/env python3
"""Offline adapter from original CPG source assets to the bounded native recipes."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--kind', choices=['tree-sitter', 'menhir'], required=True)
parser.add_argument('--recipe', type=Path, required=True)
parser.add_argument('--assets', type=Path, required=True)
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--prefix', type=Path, required=True)
parser.add_argument('--jobs', type=int, default=4)
args = parser.parse_args()
recipe, assets, build, prefix = (x.resolve() for x in (args.recipe, args.assets, args.build, args.prefix))
kind = 'tree' if args.kind == 'tree-sitter' else 'menhir'
shutil.copytree(recipe / (kind + '-inputs'), assets, dirs_exist_ok=True)
stage = build / 'staged-install'
if stage.exists():
    raise FileExistsError(stage)
if args.kind == 'tree-sitter':
    subprocess.run([sys.executable, '-B', str(assets / 'tools/build.py'),
                    '--source-dir', str(build / 'pristine-source'), '--build-dir', str(build / 'objects'),
                    '--prefix', str(stage), '--evidence-dir', str(build / 'source-evidence')], check=True)
    for name in ('api.py', 'verify.py', 'source-lock.json', 'README.zh.txt'):
        shutil.copy2(assets / name, stage / name)
else:
    compile_root = build / 'compile'
    subprocess.run([sys.executable, '-B', str(assets / 'recipe/build.py'), '--source', str(assets),
                    '--build', str(compile_root), '--evidence', str(build / 'source-evidence'),
                    '--jobs', str(args.jobs)], check=True)
    subprocess.run([sys.executable, '-B', str(assets / 'recipe/install.py'), '--source', str(assets),
                    '--build', str(compile_root), '--prefix', str(stage),
                    '--evidence', str(build / 'source-install-evidence')], check=True)
    # Bounded check source and exact source archives remain available after relocation.
    for name in ('materials', 'recipe', 'examples'):
        shutil.copytree(assets / name, stage / 'share/cpg-menhir/replay' / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
if {p.name for p in prefix.iterdir()} != {'.cpg-prefix.json'}:
    raise RuntimeError('Expected only the original Manager ownership marker in fresh prefix')
shutil.copytree(stage, prefix, dirs_exist_ok=True, symlinks=True)
