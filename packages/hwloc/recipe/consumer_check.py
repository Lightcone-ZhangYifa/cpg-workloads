#!/usr/bin/env python3
"""Compile fresh shared/static C clients using this installed prefix only."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

RESOURCE = 'hwloc'
LIBRARY = 'hwloc'
MODULE = 'hwloc'


def validate_dynamic(text, prefix):
    paths = [line.partition("=")[2] for line in text.splitlines() if line.startswith("loaded_library=")]
    if len(paths) != 1 or Path(paths[0]).resolve(strict=True) != (prefix / "lib" / ("lib"+LIBRARY+".so")).resolve(strict=True):
        raise ValueError("Dynamic API client did not load this installed library")
    if RESOURCE+" API passed:" not in text:
        raise ValueError("API operations did not report success")
    return paths[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    commands = []
    result = {"status": "failed", "check": RESOURCE+"-fresh-shared-static-consumers", "commands": commands}
    try:
        prefix = args.prefix.resolve(strict=True)
        env = dict(os.environ, LC_ALL="C", PKG_CONFIG_LIBDIR=str(prefix/"lib/pkgconfig"))
        for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PKG_CONFIG_PATH", "PKG_CONFIG_SYSROOT_DIR", "CPATH", "C_INCLUDE_PATH", "LIBRARY_PATH"):
            env.pop(name, None)
        def run(argv, *, timeout=60):
            p = subprocess.run([str(x) for x in argv], text=True, capture_output=True, env=env, timeout=timeout)
            commands.append({"argv": [str(x) for x in argv], "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr})
            if p.returncode:
                raise ValueError("Consumer command failed: "+str(argv[0]))
            return p.stdout
        flags = shlex.split(run(["pkg-config", "--cflags", "--libs", MODULE]))
        static_flags = shlex.split(run(["pkg-config", "--cflags", "--libs", "--static", MODULE]))
        if "-l"+LIBRARY not in flags or "-l"+LIBRARY not in static_flags:
            raise ValueError("The package's own pkg-config metadata lacks its library")
        with tempfile.TemporaryDirectory(prefix="cpg-"+RESOURCE+"-consumer-") as temporary:
            directory = Path(temporary)
            shared = directory/"shared-client"
            static = directory/"static-client"
            source = prefix/"share/doc"/RESOURCE/"api-check.c"
            run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", source, *flags,
                 "-Wl,-rpath,"+str(prefix/"lib"), "-ldl", "-o", shared])
            result["dynamic_library"] = validate_dynamic(run([shared]), prefix)
            static_flags = [str(prefix/"lib"/("lib"+LIBRARY+".a")) if x == "-l"+LIBRARY else x for x in static_flags]
            run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-DCPG_STATIC_PROBE", source,
                 *static_flags, "-o", static])
            output = run([static])
            if "link_mode=static" not in output or RESOURCE+" API passed:" not in output:
                raise ValueError("Static consumer did not execute the expected API operations")
            dynamic = run(["readelf", "-d", static])
            if "lib"+LIBRARY+".so" in dynamic:
                raise ValueError("Static consumer unexpectedly depends on the shared resource library")
        result["status"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["reason"] = str(error)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
