#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--source', required=True, type=Path)
p.add_argument('--prefix', required=True, type=Path)
a = p.parse_args()
if not (a.source / 'taskflow/taskflow.hpp').is_file():
    raise SystemExit('Taskflow source tree missing')
shutil.copytree(a.source / 'taskflow', a.prefix / 'include/taskflow')
share = a.prefix / 'share/taskflow'
share.mkdir(parents=True)
for name in ('LICENSE', 'README.md'):
    shutil.copy2(a.source / name, share / name)
for name in ('examples', 'unittests', '3rd-party/doctest'):
    shutil.copytree(a.source / name, share / name)
print('TASKFLOW_SOURCE_INSTALL_OK')
