"""Write every check attempt to the independent CPG build tree, never payload."""

if not __debug__:
    raise RuntimeError("Python optimization mode is unsupported for this verified entrypoint; unset PYTHONOPTIMIZE and omit -O/-OO.")
import json
from pathlib import Path
import subprocess
import sys
import tempfile

prefix=Path(sys.argv[1]).resolve()
build=Path(sys.argv[2]).resolve()
build.mkdir(parents=True,exist_ok=True)
out=Path(tempfile.mkdtemp(prefix='worker006-functional-',dir=build))
result=subprocess.run([sys.executable,str(prefix/'recipe/check.py'),str(out)],text=True,capture_output=True,timeout=180)
(out/'adapter.stdout.log').write_text(result.stdout)
(out/'adapter.stderr.log').write_text(result.stderr)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
print(json.dumps({'cpg_functional_evidence':str(out),'returncode':result.returncode}))
raise SystemExit(result.returncode)
