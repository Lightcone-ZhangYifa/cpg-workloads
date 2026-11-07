#!/usr/bin/env python3
"""Move the installed prefix and hide bootstrap while re-running all checks."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from common import configure, write_json

p=argparse.ArgumentParser()
p.add_argument("--source")
p.add_argument("--build")
p.add_argument("--prefix",required=True)
p.add_argument("--evidence")
a=p.parse_args()
ROOT,WORK,EVIDENCE=configure(a.source,a.build,a.evidence)
prefix=Path(a.prefix).resolve()
relocated=prefix.with_name(prefix.name+"-relocated")
bootstrap=WORK/"bootstrap"
hidden=WORK/"bootstrap-hidden-for-relocation"
if relocated.exists() or hidden.exists():
    raise SystemExit("Refusing to overwrite an existing relocation path")
if not prefix.is_dir() or not bootstrap.is_dir():
    raise SystemExit("Expected completed build and install directories")
prefix.rename(relocated)
bootstrap.rename(hidden)
try:
    command=[sys.executable,str(ROOT/"recipe/check.py"),"--source",str(ROOT),
             "--build",str(WORK/"relocation-checks"),"--prefix",str(relocated),
             "--evidence",str(EVIDENCE/"relocation-check")]
    result=subprocess.run(command)
    record={"schema_version":1,"success":result.returncode==0,
            "original_prefix":str(prefix),"relocated_prefix":str(relocated),
            "original_bootstrap_hidden":True,"returncode":result.returncode,
            "command":command,
            "scope":"Same-host Linux x86_64/glibc prefix relocation; does not establish cross-architecture or cross-libc portability."}
    check=EVIDENCE/"relocation-check/check.json"
    if check.is_file():
        r=json.loads(check.read_text());record["case_count"]=r["case_count"];record["passed"]=r["passed"]
    write_json(EVIDENCE/"relocation.json",record)
finally:
    hidden.rename(bootstrap)
    relocated.rename(prefix)
if result.returncode:
    raise SystemExit(result.returncode)
print("RELOCATION_PASS")
