#!/usr/bin/env python3
"""Bounded checks for the same ABI Cafe source/binary resource definition."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--kind", choices=("availability", "functional"), required=True)
    args = parser.parse_args()
    if sys.flags.optimize:
        raise RuntimeError("Optimized Python is not permitted")
    args.prefix, args.build = args.prefix.resolve(), args.build.resolve()
    if args.prefix == args.build or args.prefix in args.build.parents or args.build in args.prefix.parents:
        raise ValueError("Installed prefix and check output must be independent trees")
    recipe = Path(__file__).resolve().parent
    lock = json.loads((recipe / "source-inputs.json").read_text())
    for row in lock["inputs"]:
        path = args.prefix / row["path"]
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        if path.stat().st_size != row["size"] or h.hexdigest() != row["sha256"]:
            raise ValueError("Installed source/vendor archive differs from the frozen input")
    env = {**os.environ, "CARGO_NET_OFFLINE": "true", "TOKIO_WORKER_THREADS": "1", "RAYON_NUM_THREADS": "1", "CARGO_BUILD_JOBS": "1"}
    version = subprocess.check_output([str(args.prefix / "toolchain/bin/rustc"), "-vV"], env=env, text=True)
    if not version.startswith("rustc 1.88.0 "):
        raise ValueError("Bundled Rust compiler version differs")
    subprocess.run([str(args.prefix / "bin/abi-cafe"), "--help"], env=env, check=True, stdout=subprocess.DEVNULL)
    result = {"status": "passed", "kind": args.kind, "source_commit": lock["commit"], "vendored_crates": lock["vendor_crates"]}
    if args.kind == "functional":
        args.build.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="abi-cafe-check-", dir=args.build))
        command = [sys.executable, "-B", str(recipe / "check-cafe.py"), "--root", str(args.prefix), "--out", str(output), "--smoke"]
        with (args.build / (output.name + ".stdout.log")).open("w") as stdout, (args.build / (output.name + ".stderr.log")).open("w") as stderr:
            process = subprocess.run(command, env=env, stdout=stdout, stderr=stderr)
        if process.returncode:
            raise RuntimeError(f"Installed ABI Cafe functional test failed; see {output}")
        report = json.loads((output / "results.json").read_text())
        if report["status"] != "passed" or report["positive_test_combinations"] != 2:
            raise ValueError("Functional report did not establish both call directions")
        result.update(positive_test_combinations=2, report=str(output / "results.json"),
                      scope="FixedAggregate, graffiti, GCC calls Rust and Rust calls GCC; descriptive compatibility only")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
