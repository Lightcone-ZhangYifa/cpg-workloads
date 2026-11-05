#!/usr/bin/env python3
"""Exercise libpfm enumeration and its public C API without opening counters."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def validate(text):
    rows = [line for line in text.splitlines()
            if re.search(r"0x[0-9a-fA-F]+", line) and "::" in line]
    if not rows:
        raise ValueError("libpfm returned no encoded named event")
    return len(rows)


def validate_api(value, prefix, *, static=False):
    if (not isinstance(value, dict) or value.get("api_version") != "4.0"
            or type(value.get("supported_pmus")) is not int or value["supported_pmus"] < 1
            or type(value.get("detected_pmus")) is not int or value["detected_pmus"] < 0
            or value.get("encoded_events") != 3 or value.get("invalid_event_rejected") is not True
            or value.get("counter_collection_qualified") is not False):
        raise ValueError("libpfm public API results do not satisfy the declared operations")
    if static:
        if value.get("library_path") != "static":
            raise ValueError("The static consumer did not report static linkage")
        return value
    expected = (prefix / "lib/libpfm.so.4.13.0").resolve(strict=True)
    actual = Path(value.get("library_path", "")).resolve(strict=True)
    if actual != expected:
        raise ValueError("The API probe loaded libpfm from another installation: " + str(actual))
    return value


def validate_upstream(text):
    tables = re.findall(r"checking (\S+) \((\d+) events\): (\S+)", text)
    if len(tables) != 386 or any(status != "Passed" for _,_,status in tables):
        raise ValueError("The pinned x86 libpfm table validator did not pass every expected table")
    if ("1181 x86 events: 0 errors" not in text or "3 perf_events generic events: 0 errors" not in text
            or "All tests passed" not in text):
        raise ValueError("The upstream architecture/perf encoding cases did not all run successfully")
    return {"event_tables": len(tables), "table_event_entries": sum(int(count) for _,count,_ in tables),
            "x86_encoding_cases": 1181, "perf_encoding_cases": 3, "counter_collection": "not_run"}


def run(argv, commands, *, env, timeout=30):
    started = time.monotonic()
    result = subprocess.run([str(a) for a in argv], env=env, capture_output=True, text=True, timeout=timeout)
    commands.append({"argv": [str(a) for a in argv], "returncode": result.returncode,
                     "duration_seconds": time.monotonic()-started, "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode != 0:
        raise ValueError("Resource operation returned a nonzero status: " + str(argv[0]))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--check", choices=("encoding", "c-api", "compile-link", "upstream-validator"), default="encoding")
    args = parser.parse_args()
    commands = []
    result = {"status": "failed", "check": "libpfm-"+args.check,
              "counter_collection_qualified": False, "commands": commands}
    try:
        prefix = args.prefix.resolve(strict=True)
        env = dict(os.environ, LC_ALL="C")
        # Test this installation's RUNPATH, not an ambient loader override.
        env.pop("LD_LIBRARY_PATH", None)
        env.pop("LD_PRELOAD", None)
        if args.check == "encoding":
            text = run([prefix / "bin/showevtinfo", "-E"], commands, env=env)
            result["encoded_events"] = validate(text)
        elif args.check == "c-api":
            text = run([prefix / "bin/libpfm-api-check"], commands, env=env)
            result["api"] = validate_api(json.loads(text), prefix)
        elif args.check == "upstream-validator":
            text = run([prefix / "bin/libpfm-validate", "-A"], commands, env=env, timeout=120)
            result["upstream"] = validate_upstream(text)
        else:
            with tempfile.TemporaryDirectory(prefix="cpg-libpfm-api-") as directory:
                executable = Path(directory)/"api-probe"
                run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                     "-I"+str(prefix/"include"), prefix/"share/compiler-playground/libpfm4/api-check.c",
                     "-L"+str(prefix/"lib"), "-Wl,-rpath,"+str(prefix/"lib"),
                     "-lpfm", "-ldl", "-o", executable], commands, env=env, timeout=60)
                text = run([executable], commands, env=env)
                result["api"] = validate_api(json.loads(text), prefix)
                static = Path(directory)/"static-probe"
                run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-DCPG_STATIC_PROBE",
                     "-I"+str(prefix/"include"), prefix/"share/compiler-playground/libpfm4/api-check.c",
                     prefix/"lib/libpfm.a", "-o", static], commands, env=env, timeout=60)
                result["static_api"] = validate_api(json.loads(run([static], commands, env=env)), prefix, static=True)
        result["status"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["reason"] = str(error)
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
