#!/usr/bin/env python3
"""Check the installed QBE backend and its original upstream tests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--case", required=True, choices=("compile-run-and-reject", "upstream-tests"))
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    executable = prefix / "bin/qbe"
    result = {"status": "running", "case": args.case, "prefix": str(prefix),
              "executable_sha256": sha(executable), "commands": []}

    def run(argv, *, env=None, expected=0, timeout=180):
        argv = [str(item) for item in argv]
        completed = subprocess.run(argv, text=True, capture_output=True, env=env, timeout=timeout)
        row = {"argv": argv, "returncode": completed.returncode,
               "stdout": completed.stdout, "stderr": completed.stderr}
        result["commands"].append(row)
        if completed.returncode != expected:
            raise RuntimeError("Unexpected command result: " + json.dumps(row))
        return completed

    try:
        with tempfile.TemporaryDirectory(prefix="cpg-qbe-check-") as temporary:
            work = Path(temporary)
            if args.case == "compile-run-and-reject":
                program = work / "sum.ssa"
                program.write_text("export function w $cpg_sum(w %a, w %b) {\n@start\n %c =w add %a, %b\n ret %c\n}\n")
                driver = work / "driver.c"
                driver.write_text('#include <stdio.h>\nextern int cpg_sum(int,int);\n'
                                  'int main(void) { if (cpg_sum(17,25)!=42 || cpg_sum(-42,42)!=0) return 1; puts("qbe compiled result: 42"); return 0; }\n')
                run([executable, "-t", "amd64_sysv", "-o", work / "sum.s", program])
                run(["/usr/bin/cc", driver, work / "sum.s", "-o", work / "program"])
                output = run([work / "program"])
                if output.stdout.strip() != "qbe compiled result: 42":
                    raise RuntimeError("Compiled program returned unexpected output")
                invalid = work / "invalid.ssa"
                invalid.write_text("export function w $bad() {\n@start\n %x =w not_an_opcode 1, 2\n ret %x\n}\n")
                rejected = run([executable, "-o", work / "invalid.s", invalid], expected=1)
                if "invalid" not in rejected.stderr.lower() and "unknown" not in rejected.stderr.lower():
                    raise RuntimeError("Malformed SSA did not produce a parser diagnostic")
                result.update(native_target="amd64_sysv", invalid_ssa="rejected", official_benchmark=False)
            else:
                # The official runner uses one process-global /tmp filename. Keep
                # its test logic intact, but isolate that filename for this run.
                original = Path(__file__).with_name("upstream-test.sh")
                script = original.read_text()
                if script.count("tmp=/tmp/qbe.zzzz") != 1:
                    raise RuntimeError("Upstream temporary-file declaration changed")
                (work / "tools").mkdir()
                runner = work / "tools/test.sh"
                runner.write_text(script.replace("tmp=/tmp/qbe.zzzz", "tmp=" + shlex.quote(str(work / "scratch"))))
                shutil.copytree(prefix / "share/qbe/test", work / "test")
                (work / "qbe").symlink_to(executable)
                env = dict(os.environ, bin=str(work / "qbe"), CC="/usr/bin/cc", LC_ALL="C")
                env.pop("TARGET", None)
                env.pop("binref", None)
                completed = run(["/bin/sh", runner, "all"], env=env)
                if "All is fine!" not in completed.stdout or "[ok]" not in completed.stdout:
                    raise RuntimeError("Upstream runner did not confirm successful test execution")
                result.update(upstream_runner_sha256=sha(original),
                              adaptation="Only the fixed tmp=/tmp/qbe.zzzz prefix is replaced in a temporary copy; original installed runner and test cases are unchanged.",
                              upstream_cases_passed=completed.stdout.count("[ok]"),
                              upstream_test_files=len(list((work / "test").glob("[!_]*.ssa"))),
                              cross_architecture_tests="not_run", official_benchmark=False)
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
