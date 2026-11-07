#!/usr/bin/env python3
"""CPG source installer: only immutable local inputs, no network preparation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--offline-inputs", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    workspace = args.build.resolve() / "source"
    shutil.copytree(args.offline_inputs.resolve(), workspace)
    shutil.copytree(args.upstream.resolve(), workspace / "assets/pliron-source")
    build = args.build.resolve() / "cargo-build"
    command = ["python3", str(workspace / "recipes/build-pliron.py"),
               "--source-root", str(workspace), "--work-dir", str(build),
               "--jobs", str(args.jobs)]
    result = subprocess.run(command, check=False)
    if result.returncode:
        return result.returncode
    destination = args.prefix.resolve() / "share/pliron"
    shutil.copytree(workspace, destination)
    binary = args.prefix.resolve() / "bin/cpg-pliron-probe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / "target/debug/cpg-pliron-probe", binary)
    os.chmod(binary, 0o755)
    print(json.dumps({"installed": str(args.prefix), "network_acquisition": False,
                      "source_build": True, "cargo_locked": True, "cargo_offline": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
