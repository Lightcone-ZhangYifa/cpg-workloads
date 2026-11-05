#!/usr/bin/env python3
"""Trace real dynamic-library calls with the selected ltrace and prototype file."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SOURCE = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc != 3) return 90;
    const char *text = "cpg-ltrace-probe";
    size_t size = strlen(text);
    if (size != 16) return 91;
    char *copy = malloc(size + 1);
    if (!copy) return 92;
    strcpy(copy, text);
    FILE *stream = fopen(argv[1], "w");
    if (!stream) return 93;
    if (fputs(copy, stream) < 0 || fclose(stream) != 0) return 94;
    puts(copy);
    free(copy);
    return atoi(argv[2]);
}
'''


def denied(stderr):
    lower = stderr.lower()
    return ("ptrace" in lower or "traceme" in lower or "couldn't trace" in lower) and ("operation not permitted" in lower or "permission denied" in lower)


def validate_trace(text, *, output_file, exit_code):
    for name in ("strlen", "malloc", "strcpy", "fopen", "fputs", "fclose", "puts", "free"):
        if re.search(r"\b" + name + r"\(", text) is None:
            raise ValueError("Expected dynamic call was not traced: " + name)
    if re.search(r'strlen\("cpg-ltrace-probe"\)\s+= 16\b', text) is None:
        raise ValueError("The real string argument and returned length were not decoded")
    if output_file not in text or f"exited (status {exit_code})" not in text:
        raise ValueError("The traced file argument or child exit record differs")


def qualify(args, evidence):
    launcher = [str(args.tool)]
    if args.loader:
        if not args.library_path:
            raise ValueError("A private loader requires its matching private library path")
        launcher = [str(args.loader), "--library-path", args.library_path, str(args.tool)]
    commands = evidence.setdefault("commands", [])

    def run(argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                                env=dict(os.environ, LC_ALL="C"), check=False)
        commands.append({"argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        return result

    version = run(launcher + ["--version"])
    if version.returncode != 0 or re.search(r"^ltrace (?:version )?" + re.escape(args.expected_version) + r"\.?(?:\n|$)", version.stdout) is None:
        raise ValueError("The selected ltrace upstream version differs")
    if args.version_only:
        return {"status": "passed", "check": "upstream-version", "commands": commands}
    compiler = shutil.which("cc")
    if compiler is None or not args.config.is_file():
        return {"status": "blocked", "reason": "The C compiler and ltrace prototype configuration are required", "commands": commands}
    traces = evidence.setdefault("traces", [])
    with tempfile.TemporaryDirectory(prefix="cpg-ltrace-") as directory:
        root = Path(directory)
        source, executable = root / "probe.c", root / "probe"
        source.write_text(SOURCE)
        compiled = run([compiler, "-std=c11", "-O0", "-g", "-fno-builtin", "-fno-pie", "-no-pie", str(source), "-o", str(executable)])
        if compiled.returncode:
            raise ValueError("The dynamic-call fixture could not be compiled")
        for exit_code in (0, 7):
            output, trace = root / f"output-{exit_code}", root / f"trace-{exit_code}.txt"
            result = run(launcher + ["-F", str(args.config), "-s", "256", "-e", "strlen+malloc+strcpy+fopen+fputs+fclose+puts+free",
                                     "-o", str(trace), str(executable), str(output), str(exit_code)])
            text = trace.read_text() if trace.is_file() else ""
            traces.append({"target_exit_code": exit_code, "ltrace_returncode": result.returncode, "raw_trace": text})
            if denied(result.stderr + "\n" + text):
                return {"status": "blocked", "reason": "The execution context denies ptrace for the newly created child",
                        "commands": commands, "trace": text, "ptrace_configuration_changed": False}
            # ltrace 0.7.3 records the target exit status but its own process can
            # return zero for a target failure. Never treat that as target success.
            if result.returncode != 0 or result.stdout != "cpg-ltrace-probe\n" or not output.is_file() or output.read_text() != "cpg-ltrace-probe":
                raise ValueError("The traced child output/artifact or ltrace process status differs")
            validate_trace(text, output_file=str(output), exit_code=exit_code)
    return {"status": "passed", "check": "dynamic-calls-and-target-exit-record", "commands": commands, "traces": traces,
            "scope": "Native dynamically linked non-PIE C fixture using PLT calls and the exact ltrace prototype configuration; not arbitrary optimized/static/PIE binaries or foreign-process attachment."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", type=Path, default=Path("/usr/bin/ltrace"))
    parser.add_argument("--config", type=Path, default=Path("/etc/ltrace.conf"))
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--library-path")
    parser.add_argument("--expected-version", default="0.7.3")
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    evidence = {}
    try:
        result = qualify(args, evidence)
    except Exception as error:
        result = {"status": "failed", "reason": str(error), "error_type": type(error).__name__, **evidence}
    print(json.dumps(result, indent=2))
    return {"passed": 0, "blocked": 77, "failed": 1}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
