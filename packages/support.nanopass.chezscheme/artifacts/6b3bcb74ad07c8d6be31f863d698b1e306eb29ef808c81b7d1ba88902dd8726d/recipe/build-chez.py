#!/usr/bin/env python3
"""Build the Chez portable C kernel; reuse the exact upstream pb boot files.

This is the documented ``--pb`` / ``make kernel`` route, not a native Chez
bootstrap or a recompiled Scheme heap. No network is used.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--source", type=Path, required=True)
p.add_argument("--build", type=Path, required=True)
p.add_argument("--prefix", type=Path, required=True)
p.add_argument("--jobs", type=int, default=2)
a = p.parse_args()
if a.jobs < 1:
    raise SystemExit("jobs must be positive")
for relative in ("configure", "boot/pb/petite.boot", "boot/pb/scheme.boot", "nanopass/nanopass.ss", "zuo/zuo.c", "zlib/zlib.h", "lz4/lib/lz4.h"):
    if not (a.source / relative).is_file():
        raise SystemExit("The offline source closure is incomplete: " + relative)
a.build.mkdir(parents=True, exist_ok=True)
temporary = a.build / "tmp"
temporary.mkdir(exist_ok=True)
env = {**os.environ, "TMPDIR": str(temporary.resolve())}
subprocess.run([str(a.source.resolve() / "configure"), "--pb", "--installprefix=" + str(a.prefix.resolve()), "--disable-curses", "--disable-x11"], cwd=a.build, env=env, check=True)
subprocess.run(["make", "-j" + str(a.jobs), "kernel"], cwd=a.build, env=env, check=True)
subprocess.run(["make", "install"], cwd=a.build, env=env, check=True)
licenses = a.prefix / "share/licenses/chezscheme"
for relative in ("LICENSE", "NOTICE", "nanopass/Copyright", "lz4/LICENSE", "lz4/lib/LICENSE", "zlib/LICENSE", "zuo/LICENSE.txt", "stex/Copyright"):
    source = a.source / relative
    if source.is_file():
        destination = licenses / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
