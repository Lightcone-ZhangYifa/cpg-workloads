#!/usr/bin/env python3
"""Give a declared upstream check a fresh workspace on every invocation."""
import argparse,json,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('argv',nargs=argparse.REMAINDER);a=p.parse_args();argv=a.argv
if argv and argv[0]=='--':argv=argv[1:]
if not argv:raise SystemExit('A command is required')
a.base.mkdir(parents=True,exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='check-',dir=a.base));work=root/'work'
command=[s.replace('@WORK@',str(work)) for s in argv]
(root/'invocation.json').write_text(json.dumps({'argv':command,'work_directory':str(work)},indent=2)+'\n')
r=subprocess.run(command)
(root/'exit.json').write_text(json.dumps({'returncode':r.returncode})+'\n')
raise SystemExit(r.returncode)
