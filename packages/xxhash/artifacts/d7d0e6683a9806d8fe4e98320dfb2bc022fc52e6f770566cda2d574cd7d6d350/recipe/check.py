"""Check the selected xxHash installation without relying on a host xxhsum."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(prefix: Path, *, version_only=False):
    prefix = prefix.resolve(strict=True)
    env = dict(os.environ, LC_ALL="C")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        env.pop(key, None)
    commands = []

    def run(argv, *, cwd=None, expected=0):
        result = subprocess.run([str(p) for p in argv], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=30)
        row = {"argv": [str(p) for p in argv], "returncode": result.returncode,
               "stdout": result.stdout, "stderr": result.stderr}
        commands.append(row)
        if (expected == 0 and result.returncode != 0) or (expected == "nonzero" and result.returncode == 0):
            raise RuntimeError(json.dumps(row))
        return result.stdout + result.stderr

    cli = prefix / "bin/xxhsum"
    version = run([cli, "--version"])
    if "xxhsum 0.8.4" not in version:
        raise RuntimeError("The selected CLI is not xxhsum 0.8.4: " + version)
    if version_only:
        return {"status": "passed", "kind": "version", "version": "0.8.4", "commands": commands}
    api = run([prefix / "bin/cpg-xxhash-api-probe"])
    details = dict(line.split("=", 1) for line in api.splitlines() if "=" in line)
    loaded = Path(details["library"]).resolve(strict=True)
    if loaded.parent != prefix / "lib" or details.get("version") != "0.8.4":
        raise RuntimeError("The C API probe loaded a different installation: " + str(loaded))
    if int(details["upstream_vectors"]) < 33000 or int(details["streaming_alignment_cases"]) != 1408:
        raise RuntimeError("Incomplete installed-library vector coverage")
    with tempfile.TemporaryDirectory(prefix="cpg-xxhash-check-") as directory:
        work = Path(directory)
        sample = work / "sample with spaces.bin"
        original = bytes(range(256)) * 4096 + b"xxHash integration\x00"
        sample.write_bytes(original)
        for algorithm in (0, 1, 2, 3):
            checksums = work / f"algorithm-{algorithm}.xxh"
            output = run([cli, f"-H{algorithm}", sample.name], cwd=work)
            checksums.write_text(output)
            run([cli, "--check", checksums.name], cwd=work)
            sample.write_bytes(original + b"corruption")
            run([cli, "--check", checksums.name], cwd=work, expected="nonzero")
            sample.write_bytes(original)
        run([cli, "-H9", sample.name], cwd=work, expected="nonzero")
    return {"status": "passed", "kind": "functional", "api": details,
            "scope": "Installed shared-library upstream vectors, streaming/alignment, four CLI algorithms and corruption rejection.",
            "benchmark_score": None, "commands": commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.prefix, version_only=args.version_only), indent=2))


if __name__ == "__main__":
    main()
