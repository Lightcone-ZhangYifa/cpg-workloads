#!/usr/bin/env python3
"""Compile a new single-file Haskell client against a selected offline Megaparsec build."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

# This helper is installed inside an integrity-checked prefix. Importing its
# sibling must not create a __pycache__ entry in that installed payload.
sys.dont_write_bytecode = True
from client_runtime import plain, sha256, source_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build, project, receipt, environment = source_runtime(args.build_dir)
    source, output = plain(args.source), plain(args.output)
    if not source.is_file() or source.suffix not in {".hs", ".lhs"}:
        raise ValueError("--source must be an ordinary Haskell source file")
    if output.exists() or output.is_symlink():
        raise FileExistsError("The output must be a new file")
    if not output.parent.is_dir():
        raise ValueError("The output parent directory must already exist")
    if output.is_relative_to(project) or output.is_relative_to(build / "toolchain"):
        raise ValueError("The output cannot modify the locked project or toolchain")
    parent = plain(build / "client-builds")
    parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="client-", dir=parent))
    copied = work / source.name
    source_hash = sha256(source)
    shutil.copy2(source, copied)
    if sha256(copied) != source_hash or sha256(source) != source_hash:
        raise ValueError("The client source changed during independent copying")
    objects = work / "objects"
    objects.mkdir()
    binary = work / "program"
    tools = receipt["toolchain"]
    command = [tools["cabal"], "--config-file=cabal.config", "v2-exec", "--offline",
               "--with-compiler=" + tools["ghc"], "--", tools["ghc"],
               "-package", "megaparsec", "-package", "containers", str(copied),
               "-outputdir", str(objects), "-o", str(binary)]
    record = {"schema_version": 1, "status": "running", "scope": "A fresh Haskell library consumer; the program is compiled but not executed.",
              "resource_id": "megaparsec", "source": str(source), "source_sha256": source_hash,
              "copied_source": str(copied), "project": str(project), "argv": command,
              "output": str(output), "network_acquisition": False}
    started = time.monotonic()
    try:
        with (work / "stdout.log").open("wb") as out, (work / "stderr.log").open("wb") as err:
            result = subprocess.run(command, cwd=project, env=environment, stdout=out, stderr=err, timeout=600, check=False)
        record["returncode"] = result.returncode
        if result.returncode or not binary.is_file():
            raise RuntimeError("Client compilation failed; see " + str(work / "stderr.log"))
        descriptor, temporary_name = tempfile.mkstemp(prefix=".cpg-client-", dir=output.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(binary, temporary)
            if sha256(temporary) != sha256(binary):
                raise ValueError("The client output copy differs from the actual compiler artifact")
            os.link(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        record.update(status="passed", output_sha256=sha256(output), bytes=output.stat().st_size)
    except BaseException as error:
        record.update(status="failed", reason=str(error))
        raise
    finally:
        record["elapsed_seconds"] = time.monotonic() - started
        (work / "compile-receipt.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(json.dumps({**record, "receipt": str(work / "compile-receipt.json")}), flush=True)


if __name__ == "__main__":
    main()
