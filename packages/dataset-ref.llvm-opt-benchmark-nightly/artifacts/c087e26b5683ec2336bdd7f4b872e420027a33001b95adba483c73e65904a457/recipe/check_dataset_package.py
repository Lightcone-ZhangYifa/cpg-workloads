#!/usr/bin/env python3
"""Native PackageManager check with an explicit, byte-locked external compiler."""
import argparse
import os
from pathlib import Path
import sys
import tempfile


def main(prefix, output):
    prefix=prefix.resolve();output.mkdir(parents=True,exist_ok=True)
    run=Path(tempfile.mkdtemp(prefix='run-',dir=output))
    run.rmdir()  # check_nightly claims its fresh output itself.
    declared=os.environ.get('CPG_WORKER_LLVM_OPT')
    if not declared:raise RuntimeError('Set CPG_WORKER_LLVM_OPT to the verified worker032 toolchain opt; PATH discovery is intentionally unavailable.')
    sys.path.insert(0,str(prefix/'scripts'))
    from check_nightly import check
    check(prefix/'datasets/llvm-opt-benchmark-nightly',Path(declared),prefix/'shared-toolchain-required.json',run)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--prefix',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.prefix,a.output)
