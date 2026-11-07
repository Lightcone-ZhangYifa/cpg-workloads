"""Offline source installation hook executed by CPG 0.21.14."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource", required=True, choices=["epcc-openacc", "openacc-vv"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    resource = args.resource
    base = args.prefix / "share" / resource
    upstream = base / "upstream"
    if upstream.exists():
        raise RuntimeError("Installation tree is not fresh")
    manifest = json.loads((here / "upstream-files.json").read_text())
    actual = {p.relative_to(args.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in args.source.rglob("*") if p.is_file()}
    if actual != manifest["files"]:
        raise RuntimeError("Extracted source contents do not match the pinned upstream inventory")
    shutil.copytree(args.source, upstream)
    adapter = base / "adapter"
    adapter.mkdir(parents=True)
    for name in ["cpg_openacc.py", "inventory.json", "upstream-files.json"]:
        shutil.copy2(here / name, base / name)
    if resource == "epcc-openacc":
        shutil.copy2(here / "epcc_driver.c", adapter / "epcc_driver.c")
        binary = args.build / "epcc-openacc-kernel"
        args.build.mkdir(parents=True, exist_ok=True)
        command = ["gcc", "-O2", "-fopenacc", "-fopenmp", "-foffload=disable",
            "-I", str(upstream), str(adapter / "epcc_driver.c"), str(upstream / "level1.c"),
            str(upstream / "27stencil.c"), str(upstream / "himeno.c"), "-lm", "-o", str(binary)]
        subprocess.run(command, cwd=args.build, check=True)
        (args.prefix / "bin").mkdir(exist_ok=True)
        shutil.copy2(binary, args.prefix / "bin/epcc-openacc-kernel")
    print(json.dumps({"status": "installed", "resource": resource, "upstream_files": len(actual)}))


if __name__ == "__main__":
    main()
