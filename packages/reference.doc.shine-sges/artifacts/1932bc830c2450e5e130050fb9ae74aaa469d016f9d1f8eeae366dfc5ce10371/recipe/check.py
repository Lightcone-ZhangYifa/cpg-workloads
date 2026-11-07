#!/usr/bin/env python3
import argparse, importlib.util, json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);a=p.parse_args()
s=importlib.util.spec_from_file_location('cpg_reference',a.prefix/'tools/reference.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
print(json.dumps(m.verify(a.prefix),ensure_ascii=False,sort_keys=True))
