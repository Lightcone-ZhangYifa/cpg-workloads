"""Bounded verification of the standalone PyPI pegen distribution."""
import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import pegen

p=argparse.ArgumentParser()
p.add_argument("--version-only",action="store_true")
a=p.parse_args()
version=importlib.metadata.version("pegen")
assert version=="0.3.0",version
module=Path(pegen.__file__).resolve()
assert module.is_relative_to(Path(sys.prefix).resolve()),(module,sys.prefix)
if a.version_only:
    print(json.dumps({"status":"passed","version":version,"module":str(module)}))
    raise SystemExit(0)
root=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="cpg-pegen-check-") as temporary:
    work=Path(temporary)
    shutil.copy2(root/"expression.gram",work/"expression.gram")
    command=[sys.executable,"-I","-m","pegen","expression.gram","-o","expression_parser.py"]
    process=subprocess.run(command,cwd=work,capture_output=True,text=True,timeout=60)
    if process.returncode:
        raise RuntimeError(process.stderr)
    spec=importlib.util.spec_from_file_location("cpg_pegen_fixture",root/"fixture.py")
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    result=fixture.verify(work/"expression_parser.py")
    result.update(module_path=str(module),generator_returncode=process.returncode,
        generated_parser_sha256=hashlib.sha256((work/"expression_parser.py").read_bytes()).hexdigest())
    print(json.dumps(result,ensure_ascii=False))

