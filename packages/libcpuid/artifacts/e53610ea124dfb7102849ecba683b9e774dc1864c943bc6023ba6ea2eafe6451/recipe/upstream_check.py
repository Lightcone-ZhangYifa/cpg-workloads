#!/usr/bin/env python3
"""Run all pinned upstream CPU decoding fixtures using the installed decoder."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

EXPECTED_FIXTURES = 501


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_output(text, count):
    cases = re.findall(r'^Test \[([^\n]+)\]: (.*)$', text, re.MULTILINE)
    if count != EXPECTED_FIXTURES or len(cases) != count or any(status != 'OK' for _,status in cases):
        raise ValueError('The complete pinned upstream fixture set did not pass')
    if 'All successfull!' not in text:
        raise ValueError('Upstream runner did not report its final success marker')
    return len(cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',type=Path,required=True)
    args=parser.parse_args()
    result={'status':'failed','check':'libcpuid-official-decoding-fixtures'}
    try:
        prefix=args.prefix.resolve(strict=True)
        tests=prefix/'share/compiler-playground/libcpuid/upstream-tests'
        fixtures=sorted(p for p in tests.rglob('*') if p.is_file() and '.test' in p.suffixes)
        before={p.relative_to(tests).as_posix():sha(p) for p in fixtures}
        if len(fixtures) != EXPECTED_FIXTURES:
            raise ValueError('The upstream fixture set is incomplete')
        env=dict(os.environ,LC_ALL='C',LD_LIBRARY_PATH=str(prefix/'lib'))
        env.pop('LD_PRELOAD',None)
        with tempfile.TemporaryDirectory(prefix='cpg-libcpuid-upstream-') as temporary:
            directory=Path(temporary)
            # The official runner invokes its decoder through a shell. These
            # short local links keep its arguments safe for prefixes with spaces.
            (directory/'cpuid_tool').symlink_to(prefix/'libexec/resource-binaries/cpuid_tool')
            (directory/'test-inputs').symlink_to(tests,target_is_directory=True)
            argv=['python3',str(tests/'run_tests.py'),'./cpuid_tool','test-inputs']
            run=subprocess.run(argv,cwd=directory,env=env,capture_output=True,text=True,timeout=180)
        result.update(argv=argv,returncode=run.returncode,stdout=run.stdout,stderr=run.stderr,
                      fixture_count=len(fixtures),fixture_sha256=before)
        if run.returncode:
            raise ValueError('The official fixture runner failed')
        result['passed']=validate_output(run.stdout,len(fixtures))
        after={p.relative_to(tests).as_posix():sha(p) for p in fixtures}
        if before != after:
            raise ValueError('Fixture input or expected outputs changed during testing')
        result.update(status='passed',oracle_files_unchanged=True)
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        result['reason']=str(error)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
