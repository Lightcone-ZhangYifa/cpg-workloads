#!/usr/bin/env python3
"""Check actual testlib generators, validators, checkers and committed test refs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--case", choices=("interfaces-and-rejection", "upstream-native-regression"), required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    result = {"status": "running", "case": args.case, "prefix": str(prefix),
              "header_sha256": sha(prefix / "include/testlib.h"), "commands": [], "official_benchmark": False}
    environment = dict(os.environ, LC_ALL="C", PATH="/usr/bin:/bin")
    for key in ("CPATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "LD_LIBRARY_PATH", "LD_PRELOAD"):
        environment.pop(key, None)

    def run(argv, *, expected=0, stdin=None, cwd=None, env=None):
        command = [str(x) for x in argv]
        completed = subprocess.run(command, capture_output=True, text=True, input=stdin,
                                   cwd=cwd, env=env or environment, timeout=240)
        row = {"argv": command, "returncode": completed.returncode, "expected_returncode": expected,
               "stdin": stdin, "stdout": completed.stdout, "stderr": completed.stderr,
               "cwd": str(cwd) if cwd else None}
        result["commands"].append(row)
        if completed.returncode != expected:
            raise RuntimeError("Unexpected command result: " + json.dumps(row))
        return completed.stdout

    try:
        with tempfile.TemporaryDirectory(prefix="cpg-testlib-check-") as directory:
            temporary = Path(directory)
            source = prefix / "share/testlib/source"
            if args.case == "interfaces-and-rejection":
                profile = prefix / "share/compiler-playground/testlib/profile.json"
                examples = {"generator": "generators/igen.cpp", "validator": "validators/ival.cpp", "checker": "checkers/icmp.cpp"}
                names = {"generator": "testlib-igen", "validator": "testlib-ival", "checker": "testlib-icmp"}
                programs = {}
                for label, file in examples.items():
                    executable = prefix / "bin" / names[label] if profile.exists() else temporary / label
                    if profile.exists():
                        if not executable.is_file():
                            raise RuntimeError("The compiled package profile is missing an example tool")
                    else:
                        run(["/usr/bin/g++", "-std=c++17", "-O2", "-I" + str(prefix / "include"), source / file, "-o", executable])
                    programs[label] = executable
                result["execution_profile"] = "installed-upstream-examples" if profile.exists() else "legacy-header-source-compiled-temporarily"
                # Independently compile a consumer against the installed public
                # header even when the prebuilt examples are available.
                consumer = temporary / "header-consumer"
                run(["/usr/bin/g++", "-std=c++17", "-O2", "-I" + str(prefix / "include"),
                     source / "generators/igen.cpp", "-o", consumer])
                generated = run([programs["generator"], "17"])
                repeated = run([programs["generator"], "17"])
                consumed = run([consumer, "17"])
                if generated != repeated or generated != consumed or not 1 <= int(generated.strip()) <= 1000000:
                    raise RuntimeError("Generator range, repeatability or header/binary consistency failed")
                run([programs["validator"]], stdin="7\n")
                for invalid in ("0\n", "101\n", "7", "7\n8\n", "not-an-integer\n"):
                    run([programs["validator"]], stdin=invalid, expected=3)
                for name, contents in (("input.txt", ""), ("answer.txt", "7\n"), ("output.txt", "7\n")):
                    (temporary / name).write_text(contents)
                check = [programs["checker"], temporary / "input.txt", temporary / "output.txt", temporary / "answer.txt"]
                run(check)
                (temporary / "output.txt").write_text("8\n")
                run(check, expected=1)
                (temporary / "output.txt").write_text("not-an-integer\n")
                run(check, expected=2)
                (temporary / "output.txt").write_text("7\n")
                (temporary / "answer.txt").write_text("not-an-integer\n")
                run(check, expected=3)
                result.update(validator_negative_controls=5, checker_negative_controls=3,
                              deterministic_generator="passed", public_header_consumer="passed",
                              package_example_sources_modified=False)
            else:
                copied = temporary / "source"
                shutil.copytree(source, copied)
                tests = copied / "tests"
                case = tests / "test-004_use-test.h"
                refs = {str(p.relative_to(case)): sha(p) for p in (case / "refs").rglob("*") if p.is_file()}
                if not refs:
                    raise RuntimeError("No committed expected outputs exist for the upstream regression")
                env = dict(environment, TESTS_DIR=str(tests), TEST_DIR=str(case), CPP="g++", CPP_STANDARD="--std=c++17",
                           CPP_INCLUDE_DIR=str(copied), CPP_OPTS="-march=x86-64 -mtune=generic", MACHINE="Linux",
                           INVOCATION_ID="cpg-selected-native", VALGRIND="", TEST_REF_FORBID_GEN_REFS="true",
                           RED="", GREEN="", NC="")
                stdout = run(["/bin/bash", case / "run.sh"], cwd=case, env=env)
                if "execution matched with reference" not in stdout:
                    raise RuntimeError("Upstream regression did not compare against its committed reference")
                if {str(p.relative_to(case)): sha(p) for p in (case / "refs").rglob("*") if p.is_file()} != refs:
                    raise RuntimeError("Upstream reference files changed during qualification")
                result.update(upstream_case="test-004_use-test.h", compiler="GCC C++17",
                              committed_reference_files=refs, reference_generation="forbidden",
                              full_multi_compiler_and_Java_runner="not_run", upstream_test_scripts_modified=False)
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
