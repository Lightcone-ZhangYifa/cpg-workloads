"""Install only from an already verified Nanopass source tree; no network."""
from pathlib import Path
import argparse
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--source", type=Path, required=True)
p.add_argument("--prefix", type=Path, required=True)
a = p.parse_args()
if not (a.source / "nanopass.ss").is_file() or not (a.source / "Copyright").is_file():
    raise SystemExit("Nanopass source and license are required")
dest = a.prefix / "share/nanopass"
shutil.copytree(a.source, dest)
(a.prefix / "bin").mkdir(exist_ok=True)
launcher = a.prefix / "bin/cpg-nanopass"
launcher.write_text('''#!/bin/sh
set -eu
prefix=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${CPG_CHEZ_SCHEME:?Set CPG_CHEZ_SCHEME to the selected private Chez Scheme executable}"
exec "$CPG_CHEZ_SCHEME" --libdirs "$prefix/share/nanopass" "$@"
''')
launcher.chmod(0o755)
