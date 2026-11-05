#!/usr/bin/env python3
"""Trace real child syscalls and preserve denied-ptrace semantics."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SOURCE = r'''#include <fcntl.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv) {
    const char text[] = "cpg-strace-probe\n";
    const char out[] = "trace-child-ok\n";
    if (argc != 4) return 90;
    int fd = open(argv[1], O_CREAT | O_WRONLY | O_TRUNC, 0600);
    if (fd < 0 || write(fd, text, sizeof(text)-1) != sizeof(text)-1) return 91;
    if (close(fd) != 0) return 92;
    if (open(argv[2], O_RDONLY) != -1) return 93;
    if (write(1, out, sizeof(out)-1) != sizeof(out)-1) return 94;
    return atoi(argv[3]);
}
'''


def denied(stderr):
    lower = stderr.lower()
    return ("ptrace" in lower or "traceme" in lower) and ("operation not permitted" in lower or "permission denied" in lower)


def validate_trace(text, *, output_file, missing_file, exit_code):
    lines = text.splitlines()
    if not any("openat(" in line and output_file in line and "O_CREAT" in line for line in lines):
        raise ValueError("The real output-file open was not traced")
    if not any("openat(" in line and missing_file in line and "ENOENT" in line for line in lines):
        raise ValueError("The missing-file syscall failure was not decoded")
    if not any('write(' in line and 'cpg-strace-probe\\n' in line and re.search(r"= 17$", line) for line in lines):
        raise ValueError("The actual write and returned byte count were not traced")
    if not any(re.search(r"close\(\d+\)\s+= 0$", line) for line in lines):
        raise ValueError("A successful close was not traced")
    if not any(f"exit_group({exit_code})" in line for line in lines) or f"exited with {exit_code}" not in text:
        raise ValueError("The traced child exit status differs")


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
    if version.returncode != 0 or re.search(r"\bversion " + re.escape(args.expected_version) + r"(?:\n|$)", version.stdout) is None:
        raise ValueError("The selected strace upstream version differs")
    if args.version_only:
        return {"status": "passed", "check": "upstream-version", "commands": commands}
    compiler = shutil.which("cc")
    if compiler is None:
        return {"status": "blocked", "reason": "A C compiler named cc is required", "commands": commands}
    traces = evidence.setdefault("traces", [])
    with tempfile.TemporaryDirectory(prefix="cpg-strace-") as directory:
        root = Path(directory)
        source, executable = root / "probe.c", root / "probe"
        source.write_text(SOURCE)
        compiled = run([compiler, "-std=c11", "-O0", "-g", str(source), "-o", str(executable)])
        if compiled.returncode:
            raise ValueError("The native child fixture could not be compiled")
        for exit_code in (0, 7):
            output, missing, trace = root / f"output-{exit_code}", root / "intentionally-missing", root / f"trace-{exit_code}.txt"
            result = run(launcher + ["-f", "-s", "256", "-e", "trace=execve,openat,read,write,close,exit_group",
                                     "-o", str(trace), str(executable), str(output), str(missing), str(exit_code)])
            text = trace.read_text() if trace.is_file() else ""
            traces.append({"expected_exit_code": exit_code, "actual_exit_code": result.returncode, "raw_trace": text})
            if denied(result.stderr + "\n" + text):
                return {"status": "blocked", "reason": "The execution context denies ptrace for the newly created child",
                        "commands": commands, "trace": text, "ptrace_configuration_changed": False}
            if result.returncode != exit_code or result.stdout != "trace-child-ok\n" or not output.is_file() or output.read_bytes() != b"cpg-strace-probe\n":
                raise ValueError("The traced child output, artifact or exit code differs")
            validate_trace(text, output_file=str(output), missing_file=str(missing), exit_code=exit_code)
    return {"status": "passed", "check": "child-syscalls-and-exit-status", "commands": commands, "traces": traces,
            "scope": "Native Linux child syscall tracing and decoded ENOENT/exit statuses; no attachment to foreign processes or ptrace policy changes."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", type=Path, default=Path("/usr/bin/strace"))
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--library-path")
    parser.add_argument("--expected-version", default="6.8")
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

# Definition-routing fixture: this alternate recipe must be packed and run.
