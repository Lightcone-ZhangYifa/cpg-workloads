#!/usr/bin/env python3
"""Build ORC examples from two already verified local CPG source inputs."""
import argparse
import ctypes.util
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile


def safe_members(archive, selected=None):
    for member in archive:
        q = PurePosixPath(member.name)
        if q.is_absolute() or '..' in q.parts:
            raise ValueError('Unconfined archive member: '+member.name)
        if selected is None or selected(member.name):
            yield member


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk-archive', type=Path, required=True)
    parser.add_argument('--llvm-archive', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    recipe = Path(__file__).resolve().parent
    src = args.build/'independent-source'
    sdk, llvm = src/'sdk', src/'llvm'
    sdk.mkdir(parents=True, exist_ok=False)
    llvm.mkdir()
    with tarfile.open(args.sdk_archive) as t:
        t.extractall(sdk, members=safe_members(t), filter='data')
    def selected(name):
        return ('/llvm/examples/OrcV2Examples/' in name or
                name.endswith(('/llvm/docs/ORCv2.rst', '/llvm/docs/JITLink.rst',
                               '/LICENSE.TXT')))
    with tarfile.open(args.llvm_archive) as t:
        t.extractall(llvm, members=safe_members(t, selected), filter='data')
    examples = next(llvm.glob('*/llvm/examples/OrcV2Examples'))
    cmd = [sys.executable, str(recipe/'build_and_check.py'),
           '--sdk', str(sdk), '--examples', str(examples),
           '--output', str(args.build/'compiled')]
    # SDK release flags use development-library names. Bind existing ELF SONAME
    # files explicitly and record their actual hashes; never download libraries.
    import platform
    triplet = 'x86_64-linux-gnu' if platform.machine() == 'x86_64' else ''
    for name, option in [('zstd', '--zstd-library'), ('xml2', '--xml2-library')]:
        soname = ctypes.util.find_library(name)
        candidates = [Path('/usr/lib')/triplet/(soname or ''),
                      Path('/lib')/triplet/(soname or '')]
        lib = next((p.resolve() for p in candidates if p.is_file()), None)
        if lib is None:
            raise RuntimeError('Local system runtime library is required: '+name)
        cmd += [option, str(lib)]
    subprocess.run(cmd, check=True)
    shutil.copytree(args.build/'compiled/bin', args.prefix/'bin', dirs_exist_ok=True)
    shutil.copy2(recipe/'run_checks.py', args.prefix/'run_checks.py')
    share = args.prefix/'share/llvm-orc-jitlink'
    share.mkdir(parents=True, exist_ok=True)
    shutil.copytree(examples, share/'OrcV2Examples')
    source_root = next(llvm.iterdir())
    shutil.copy2(source_root/'llvm/LICENSE.TXT', share/'LLVM-LICENSE.TXT')
    for name in ['ORCv2.rst', 'JITLink.rst']:
        shutil.copy2(source_root/'llvm/docs'/name, share/name)
    shutil.copy2(args.build/'compiled/report.json', share/'build-report.json')
    shutil.copy2(recipe/'fixtures/cpg_orc_jitlink.cpp', share/'cpg_orc_jitlink.cpp')
    print(json.dumps({'status': 'passed', 'scope': 'ORC/JITLink example source build',
                      'full_llvm_source_build': False}))


if __name__ == '__main__':
    main()
