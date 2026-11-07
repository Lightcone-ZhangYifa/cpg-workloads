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
    source_path, build_path, prefix_path = args.source.resolve(), args.build.resolve(), args.prefix.resolve()
    for first, second in [(source_path, build_path), (source_path, prefix_path), (build_path, prefix_path)]:
        if first == second or first in second.parents or second in first.parents:
            raise RuntimeError("Source, build and installation paths must be disjoint")
    base = args.prefix / "share" / resource
    upstream = base / "upstream"
    if upstream.exists():
        raise RuntimeError("Installation tree is not fresh")
    manifest = json.loads((here / "upstream-files.json").read_text())
    actual = {p.relative_to(args.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in args.source.rglob("*") if p.is_file()}
    if actual != manifest["files"]:
        raise RuntimeError("Extracted source contents do not match the pinned upstream inventory")
    binary = None
    if resource == "epcc-openacc":
        # Compile exclusively from CPG's independent immutable source and frozen
        # recipe directories. Publish installation files only after success.
        binary = args.build / "epcc-openacc-kernel"
        args.build.mkdir(parents=True, exist_ok=True)
        command = ["gcc", "-O2", "-fopenacc", "-fopenmp", "-foffload=disable",
            "-I", str(args.source), str(here / "epcc_driver.c"), str(args.source / "level1.c"),
            str(args.source / "27stencil.c"), str(args.source / "himeno.c"), "-lm", "-o", str(binary)]
        subprocess.run(command, cwd=args.build, check=True)
    shutil.copytree(args.source, upstream)
    adapter = base / "adapter"
    adapter.mkdir(parents=True)
    for name in ["cpg_openacc.py", "inventory.json", "upstream-files.json"]:
        shutil.copy2(here / name, base / name)
    if resource == "epcc-openacc":
        shutil.copy2(here / "epcc_driver.c", adapter / "epcc_driver.c")
        (args.prefix / "bin").mkdir(exist_ok=True)
        shutil.copy2(binary, args.prefix / "bin/epcc-openacc-kernel")
    print(json.dumps({"status": "installed", "resource": resource, "upstream_files": len(actual),
        "build_source":str(source_path), "build_directory":str(build_path),
        "installation_prefix":str(prefix_path), "source_build_install_disjoint":True}))


if __name__ == "__main__":
    main()
