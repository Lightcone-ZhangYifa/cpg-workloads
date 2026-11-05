#!/usr/bin/env python3
"""Execute the installed JPEG codec, shared/static consumers and bad inputs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    environment = dict(os.environ, LC_ALL="C")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "LIBRARY_PATH", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
        environment.pop(key, None)
    result = {"status": "running", "prefix": str(prefix), "commands": [], "official_benchmark": False}

    def run(argv, *, expected=0, cwd=None):
        command = [str(x) for x in argv]
        completed = subprocess.run(command, capture_output=True, text=True, env=environment, cwd=cwd, timeout=120)
        result["commands"].append({"argv": command, "returncode": completed.returncode,
                                   "stdout": completed.stdout, "stderr": completed.stderr})
        if (expected is None and completed.returncode == 0) or (expected is not None and completed.returncode != expected):
            raise RuntimeError("Unexpected command return code")
        return completed

    try:
        profile = json.loads((prefix / "share/compiler-playground/libjpeg-turbo/profile.json").read_text())
        if profile.get("version") != "3.2.0" or profile.get("profile") != "scalar-full-codec" or profile.get("upstream_ctest_passed", 0) < 100:
            raise RuntimeError("Missing or mismatched package profile")
        with tempfile.TemporaryDirectory(prefix="cpg-jpeg-check-") as directory:
            temporary = Path(directory)
            for kind in ("shared", "static"):
                executable = temporary / ("api-" + kind)
                library = prefix / "lib" / ("libturbojpeg.so" if kind == "shared" else "libturbojpeg.a")
                run(["/usr/bin/gcc", "-std=c99", "-O2", "-I" + str(prefix / "include"),
                     Path(__file__).with_name("api.c"), library, "-Wl,-rpath," + str(prefix / "lib"), "-lm", "-o", executable])
                data = json.loads(run([executable]).stdout)
                if data.get("width") != 64 or data.get("height") != 48 or data.get("max_error", 99) > 3 or data.get("invalid_jpeg_rejected") is not True:
                    raise RuntimeError("The JPEG consumer returned an incomplete result")
                result[kind + "_consumer"] = data
            source = prefix / "share/libjpeg-turbo/source/testimages"
            ppm = temporary / "input.ppm"
            ppm.write_bytes(b"P6\n64 48\n255\n" + bytes([32,96,192]) * (64*48))
            jpg, decoded = temporary / "output.jpg", temporary / "decoded.ppm"
            run([prefix / "bin/cjpeg", "-quality", "100", "-sample", "1x1", "-outfile", jpg, ppm])
            run([prefix / "bin/djpeg", "-ppm", "-outfile", decoded, jpg])
            header, pixels = decoded.read_bytes().split(b"\n255\n", 1)
            if not header.startswith(b"P6\n64 48") or len(pixels) != 64*48*3:
                raise RuntimeError("Unexpected CLI decode dimensions or pixel count")
            if max(abs(a-b) for a,b in zip(pixels,bytes([32,96,192])*(64*48))) > 3:
                raise RuntimeError("CLI codec exceeded the stated color tolerance")
            rotated = temporary / "rotated.jpg"
            restored = temporary / "restored.jpg"
            run([prefix / "bin/jpegtran", "-rotate", "180", "-outfile", rotated, jpg])
            run([prefix / "bin/jpegtran", "-rotate", "180", "-outfile", restored, rotated])
            restored_ppm = temporary / "restored.ppm"
            run([prefix / "bin/djpeg", "-ppm", "-outfile", restored_ppm, restored])
            if restored_ppm.read_bytes() != decoded.read_bytes():
                raise RuntimeError("Two lossless rotations changed the decoded image")
            bad = temporary / "bad.jpg"
            bad.write_bytes(b"not a JPEG\n")
            rejected = run([prefix / "bin/djpeg", "-outfile", temporary / "bad.ppm", bad], expected=None)
            if "jpeg" not in rejected.stderr.lower():
                raise RuntimeError("Invalid input has no explicit JPEG diagnostic")
            run([prefix / "bin/cjpeg", "-cpg-invalid-option"], expected=None)
            result.update(cli_roundtrip="passed", lossless_rotation="passed", invalid_input="rejected", invalid_option="rejected")
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
