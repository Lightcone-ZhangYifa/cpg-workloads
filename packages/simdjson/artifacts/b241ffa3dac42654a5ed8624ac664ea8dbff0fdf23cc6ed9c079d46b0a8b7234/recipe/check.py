#!/usr/bin/env python3
"""Check upstream regressions and actual installed parser consumers."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

TESTS = ("unicode_tests.cpp", "padded_string_tests.cpp", "fractured_json_tests.cpp",
         "dom/array_reverse_tests.cpp", "dom/big_integer_tests.cpp", "dom/integer_tests.cpp",
         "dom/json_path_tests.cpp", "dom/random_string_number_tests.cpp", "dom/nan_inf_tests.cpp")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--case", choices=("upstream", "api"), required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    environment = dict(os.environ, LC_ALL="C")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "LIBRARY_PATH", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "SIMDJSON_FORCE_IMPLEMENTATION"):
        environment.pop(key, None)
    result = {"status": "running", "case": args.case, "prefix": str(prefix), "commands": []}

    def run(argv, *, expected=0, data=None):
        command = [str(x) for x in argv]
        completed = subprocess.run(command, input=data, text=True, capture_output=True, env=environment, timeout=240)
        result["commands"].append({"argv": command, "returncode": completed.returncode,
                                  "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode != expected:
            raise RuntimeError("Unexpected command result")
        return completed

    try:
        profile = json.loads((prefix / "share/compiler-playground/simdjson/profile.json").read_text())
        if profile.get("version") != "5.0.5" or profile.get("upstream_standalone_tests") != list(TESTS):
            raise RuntimeError("Missing or incomplete exact upstream test selection")
        if args.case == "upstream":
            for name in TESTS:
                run([prefix / "libexec/simdjson" / Path(name).stem])
            result.update(upstream_test_executables_passed=len(TESTS), source_modified=False)
        else:
            documents = [{"i": i, "negative": -i, "unicode": "编译器😀/\\\"" + str(i),
                          "nested": {"a": [None, True, False, i / 8, "line\nfeed\t"]}} for i in range(64)]
            documents += [[], {}, [1, 2, 3], {"i64": -(2**63), "u64": 2**64-1}]
            payload = "\n".join(json.dumps(x, ensure_ascii=False) for x in documents) + "\n"
            with tempfile.TemporaryDirectory(prefix="cpg-simdjson-check-") as directory:
                temporary = Path(directory)
                result["consumers"] = []
                for kind in ("shared", "static"):
                    library = prefix / "lib" / ("libsimdjson.so" if kind == "shared" else "libsimdjson_static.a")
                    executable = temporary / kind
                    run(["/usr/bin/g++", "-std=c++17", "-O2", "-I" + str(prefix / "include"),
                         Path(__file__).with_name("api.cpp"), library, "-pthread",
                         "-Wl,-rpath," + str(prefix / "lib"), "-o", executable])
                    implementations = run([executable, "--list"]).stdout.splitlines()
                    if not implementations or "fallback" not in implementations or len(set(implementations)) != len(implementations):
                        raise RuntimeError("No complete supported implementation list")
                    for implementation in implementations:
                        completed = run([executable, implementation], data=payload)
                        parsed = [json.loads(line) for line in completed.stdout.splitlines()]
                        if parsed != documents or f"implementation={implementation} documents={len(documents)}" not in completed.stderr:
                            raise RuntimeError("Parser result or actual selected implementation differs from the independent oracle")
                        for invalid in ('{"missing":}', '{"x":"unterminated}', '[1,2,]', '{"x":NaN}'):
                            failed = run([executable, implementation], expected=2, data=invalid + "\n")
                            if "Parse failed:" not in failed.stderr:
                                raise RuntimeError("Malformed JSON was not explicitly rejected")
                    run([executable, "cpg-nonexistent-implementation"], expected=65, data="{}\n")
                    result["consumers"].append({"link": kind, "implementations": implementations,
                        "documents_per_implementation": len(documents), "malformed_cases_per_implementation": 4,
                        "ondemand_value": 42, "oracle": "Python stdlib json exact decoded structures"})
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
