#!/usr/bin/env python3
"""CPG source recipe: build original Parsec, publish bounded native dev fixtures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    for flag in ("source", "build", "prefix", "tools"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    source, build, prefix, tools = [getattr(args, key).resolve() for key in ("source", "build", "prefix", "tools")]
    staged = build / "resource-input"
    shutil.copytree(tools / "bundle", staged)
    shutil.copy2(source, staged / "upstream/parsec-3.1.17.0.tar.gz")
    native = build / "native-build"
    run = subprocess.run([sys.executable, "-B", str(staged / "scripts/verify.py"), "--work-dir", str(native)], check=False)
    if run.returncode:
        raise SystemExit(run.returncode)
    result = json.loads((native / "evidence/result.json").read_text())
    if not result["passed"] or result["fixture"] != {"total": 27, "passed": 27, "failed": 0}:
        raise RuntimeError("native source build was not qualified")
    for directory in (prefix / "bin", prefix / "lib", prefix / "share/parsec"):
        directory.mkdir(parents=True, exist_ok=True)
    for name in ("parsec-fixture", "upstream-issue127"):
        shutil.copy2(native / "install/bin" / name, prefix / "bin" / name)
    for name in ("libgmp.so.10", "libffi.so.8"):
        shutil.copy2(native / "environment/root/usr/lib/x86_64-linux-gnu" / name, prefix / "lib" / name,
                     follow_symlinks=True)
    share = prefix / "share/parsec"
    shutil.copytree(native / "source/parsec-3.1.17.0", share / "source")
    shutil.copytree(staged / "licenses", share / "licenses")
    shutil.copytree(staged / "tests", share / "examples")
    shutil.copy2(source, share / "parsec-3.1.17.0.tar.gz")
    shutil.copy2(staged / "source-lock.json", share / "source-lock.json")
    shutil.copytree(native / "evidence", share / "build-evidence")
    manifest = {"schema_version": 1, "resource": "parsec", "version": "3.1.17.0",
                "capability": "source-built native development fixture plus unchanged complete Parsec source",
                "source_commit": result["source_commit"], "installed_build_package_id": result["installed_package_id"],
                "library_modules_compiled": result["library_modules_compiled"], "fixture": result["fixture"],
                "upstream_regression": result["upstream_regression"],
                "exclusions": ["The general GHC package-db and compiler environment stay in the build tree.",
                               "The relocatable published prefix does not claim an independently registered Haskell library."],
                "files": []}
    for location in (prefix / "bin", prefix / "lib"):
        for path in sorted(location.iterdir()):
            manifest["files"].append({"path": str(path.relative_to(prefix)), "sha256": sha(path), "bytes": path.stat().st_size})
    (share / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Resolve from this executable's current prefix; no build path is embedded.
    launcher = prefix / "bin/cpg-parsec-fixture"
    launcher.write_text("#!/bin/sh\nset -eu\nparsec_prefix=$(CDPATH= cd -- \"$(dirname -- \"$0\")/..\" && pwd)\n"
                        "export LD_LIBRARY_PATH=\"$parsec_prefix/lib\"\nexec \"$parsec_prefix/bin/parsec-fixture\" \"$@\"\n")
    launcher.chmod(0o755)
    print(json.dumps({"resource": "parsec", "status": "passed", "prefix": str(prefix),
                      "scope": manifest["capability"], "fixture": result["fixture"]}))


if __name__ == "__main__":
    main()
