#!/usr/bin/env python3
"""Run real installed libdivide C/C++ APIs and unmodified upstream executables."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--case", choices=("c-and-cxx-arithmetic", "upstream-tests"), required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    result = {"status": "running", "case": args.case, "prefix": str(prefix),
              "header_sha256": sha(prefix / "include/libdivide.h"), "commands": [], "official_benchmark": False}
    environment = dict(os.environ, LC_ALL="C")
    for name in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH", "LD_LIBRARY_PATH", "LD_PRELOAD"):
        environment.pop(name, None)

    def run(argv, *, expected=0, timeout=720):
        argv = [str(item) for item in argv]
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=environment)
        row = {"argv": argv, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
        result["commands"].append(row)
        if completed.returncode != expected:
            raise RuntimeError("Unexpected command result: " + json.dumps(row))
        return completed

    try:
        if args.case == "c-and-cxx-arithmetic":
            with tempfile.TemporaryDirectory(prefix="cpg-libdivide-check-") as directory:
                temporary = Path(directory)
                for compiler, standard, filename in (("/usr/bin/cc", "c99", "api.c"), ("/usr/bin/c++", "c++11", "api.cpp")):
                    executable = temporary / (filename + ".exe")
                    run([compiler, "-std=" + standard, "-O2", "-Wall", "-Wextra", "-Werror",
                         "-I" + str(prefix / "include"), Path(__file__).with_name(filename), "-o", executable])
                    answer = run([executable])
                    if "5.4.0:" not in answer.stdout or "comparisons passed" not in answer.stdout:
                        raise RuntimeError("Unexpected API fixture output/version")
                invalid = temporary / "unsupported-type.cpp"
                invalid.write_text('#include "libdivide.h"\nint main() { libdivide::divider<float> invalid(2.0f); return 0; }\n')
                rejected = run(["/usr/bin/c++", "-std=c++11", "-I" + str(prefix / "include"), invalid, "-o", temporary / "invalid"], expected=1)
                if "libdivide.h" not in rejected.stderr:
                    raise RuntimeError("Unsupported API type failed without a libdivide diagnostic")
                result.update(integer_families=["s16", "u16", "s32", "u32", "s64", "u64"],
                              branchfull=True, branchfree=True, unsupported_floating_type="rejected",
                              invalid_arithmetic_excluded=["zero denominator", "signed minimum / -1", "unsigned branchfree denominator 1"])
        else:
            tester = run([prefix / "bin/tester"])
            if "All tests passed successfully!" not in tester.stdout:
                raise RuntimeError("Upstream tester did not confirm complete execution")
            c99 = run([prefix / "bin/test_c99"])
            if "Division fail:" in c99.stderr:
                raise RuntimeError("The upstream C99 executable reported incorrect arithmetic despite its zero exit status")
            run([prefix / "bin/test_divlu"])
            rejected = run([prefix / "bin/tester", "invalid-integer-family"], expected=1)
            if "Usage: tester" not in rejected.stdout:
                raise RuntimeError("The invalid tester argument did not produce its usage diagnostic")
            result.update(upstream_test_executables=["tester", "test_c99", "test_divlu"],
                          upstream_test_sources_modified=False, tester_arguments="all six default integer families",
                          invalid_tester_argument="rejected", upstream_random_seed="upstream std::random_device; unchanged",
                          timing_benchmarks="provided, not_run as a performance qualification")
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
