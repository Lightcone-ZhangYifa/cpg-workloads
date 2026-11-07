#!/usr/bin/env python3
"""Give the original OpenCilk probe a fresh workspace on every CPG check."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--work',required=True,type=Path)
a=p.parse_args();run=a.work/('run-'+uuid.uuid4().hex)
rc=subprocess.call([sys.executable,str(Path(__file__).with_name('check.py')),'--prefix',a.prefix,'--work',str(run)])
if (run/'result.json').is_file():
    shutil.copy2(run/'result.json',a.work/'result.json')
    (a.work/'latest-run.json').write_text(json.dumps({'run':run.name,'returncode':rc})+'\n')
raise SystemExit(rc)
