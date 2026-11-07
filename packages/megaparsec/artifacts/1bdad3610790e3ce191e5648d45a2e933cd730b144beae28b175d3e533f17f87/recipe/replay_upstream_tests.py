#!/usr/bin/env python3
"""Replay the original Megaparsec tests from a verified retained offline source operation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

# Keep the installed prefix unchanged for both python3 and shebang execution.
sys.dont_write_bytecode = True
from client_runtime import plain, source_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    build, project, receipt, environment = source_runtime(args.build_dir)
    output = plain(args.output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Use a new replay evidence directory")
    if output == build or output.is_relative_to(project) or output.is_relative_to(build / "toolchain"):
        raise ValueError("Replay evidence cannot modify the locked project or toolchain")
    output.mkdir(parents=True)
    tools = receipt["toolchain"]
    command = [tools["cabal"], "--config-file=cabal.config", "v2-test", "--offline",
               "--with-compiler=" + tools["ghc"], "--jobs=" + str(args.jobs),
               "megaparsec-tests:test:tests", "--test-show-details=direct", "--test-option=--seed=20261101"]
    record = {"schema_version": 1, "status": "running", "resource_id": "megaparsec",
              "version": "9.8.3", "project": str(project), "argv": command, "seed": 20261101,
              "network_acquisition": False, "formal_qualification_increment": 0,
              "scope": "Original upstream suite with its ordinary property-test bounds, not exhaustive proof."}
    start = time.monotonic()
    try:
        with (output / "stdout.log").open("wb") as out, (output / "stderr.log").open("wb") as err:
            result = subprocess.run(command, cwd=project, env=environment, stdout=out, stderr=err, timeout=3600, check=False)
        record["returncode"] = result.returncode
        text = (output / "stdout.log").read_text(encoding="utf-8", errors="replace")
        summaries = re.findall(r"(\d+) examples?, (\d+) failures?", text)
        if result.returncode or len(summaries) != 1 or int(summaries[0][0]) < 1 or int(summaries[0][1]) != 0:
            raise RuntimeError("A successful nonempty original test run was not observed")
        record.update(status="passed", examples=int(summaries[0][0]), failures=0)
    except BaseException as error:
        record.update(status="failed", reason=str(error))
        raise
    finally:
        record["elapsed_seconds"] = time.monotonic() - start
        (output / "replay-receipt.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
