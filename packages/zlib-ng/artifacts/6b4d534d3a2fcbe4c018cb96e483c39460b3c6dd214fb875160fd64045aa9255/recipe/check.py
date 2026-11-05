"""Check the native zlib-ng ABI and gzip interoperability against Python's zlib."""
from __future__ import annotations
import argparse
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zlib


def check(prefix: Path, *, version_only=False):
    prefix = prefix.resolve(strict=True)
    library = prefix / "lib/libz-ng.so.2.3.3"
    loaded = ctypes.CDLL(str(library))
    loaded.zlibng_version.restype = ctypes.c_char_p
    version = loaded.zlibng_version().decode("ascii")
    if version != "2.3.3":
        raise RuntimeError("Selected native zlib-ng library version differs: " + version)
    if version_only:
        return {"status": "passed", "kind": "version", "version": version, "library": str(library)}
    env = dict(os.environ, LC_ALL="C")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        env.pop(key, None)
    commands, api = [], []
    def run(argv, *, data=None, expected=0):
        argv = [str(item) for item in argv]
        result = subprocess.run(argv, input=data, env=env, capture_output=True, timeout=30)
        row = {"argv": argv, "returncode": result.returncode,
               "stdin_bytes": None if data is None else len(data),
               "stdin_sha256": None if data is None else hashlib.sha256(data).hexdigest(),
               "stdout_bytes": len(result.stdout), "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
               "stderr": result.stderr.decode("utf-8", "replace")}
        commands.append(row)
        if (expected == 0 and result.returncode != 0) or (expected == "nonzero" and result.returncode == 0):
            raise RuntimeError(json.dumps(row))
        return result.stdout
    with tempfile.TemporaryDirectory(prefix="cpg-zlib-ng-check-") as directory:
        work = Path(directory)
        for linkage in ("shared", "static"):
            probe = prefix / ("bin/cpg-zlib-ng-api-probe" + ("-static" if linkage == "static" else ""))
            generated = work / (linkage + ".gz")
            output = run([probe, generated]).decode("ascii")
            details = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            expected_parent = prefix / ("lib" if linkage == "shared" else "bin")
            if (Path(details["library"]).resolve(strict=True).parent != expected_parent or
                    details.get("version") != "2.3.3" or details.get("linkage") != linkage or
                    details.get("one_shot_cases") != "15"):
                raise RuntimeError("Installed API probe selected another library or incomplete coverage")
            expected = bytes((i * 17 + i // 257) % 251 for i in range(65536))
            if gzip.decompress(generated.read_bytes()) != expected:
                raise RuntimeError("Python could not decode the C API gzip output")
            api.append(details)
        cli = prefix / "bin/zlib-ng-minigzip"
        original = bytes(range(256)) * 4096 + b"zlib-ng independent gzip interoperability\x00"
        for level in (1, 6, 9):
            compressed = run([cli, f"-{level}"], data=original)
            if gzip.decompress(compressed) != original:
                raise RuntimeError("Python disagrees with the installed upstream minigzip output")
            reference = gzip.compress(original, compresslevel=level, mtime=0)
            if run([cli, "-d"], data=reference) != original:
                raise RuntimeError("Installed minigzip disagrees with the independent reference")
            damaged = bytearray(reference)
            damaged[-8] ^= 0xff  # gzip CRC32 trailer must be checked
            run([cli, "-d"], data=bytes(damaged), expected="nonzero")
    return {"status": "passed", "kind": "functional", "native_abi": True,
            "api": api, "reference": {"implementation": "Python gzip/zlib", "zlib_version": zlib.ZLIB_RUNTIME_VERSION},
            "scope": "Native shared and static zlib-ng API; fixed checksum vectors, one-shot/streaming/dictionary/gzFile, independent gzip interoperability and CRC rejection.",
            "benchmark_score": None, "commands": commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.prefix, version_only=args.version_only), indent=2))


if __name__ == "__main__":
    main()
