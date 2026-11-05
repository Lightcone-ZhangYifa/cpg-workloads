#!/usr/bin/env python3
"""Patch real ELF loader metadata and execute every changed program variant."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


OLD_LIBRARY = "libcpg_elf_probe.so"
NEW_LIBRARY = "libcpg_elf_probe_renamed.so"
RUNPATH = "$ORIGIN/../lib"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def needed(text: str) -> set[str]:
    return set(line.strip() for line in text.splitlines() if line.strip())


def qualify(tool: Path, work: Path, *, cc: str = "cc", expected_version: str = "0.18.0") -> dict:
    tool = tool.resolve(strict=True)
    work.mkdir(parents=True, exist_ok=True)
    commands = []
    environment = dict(os.environ, LC_ALL="C", LANG="C")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT"):
        environment.pop(key, None)
    summary = {"status": "running", "check": "patchelf-executable-roundtrip", "tool": str(tool),
               "tool_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(), "work_directory": str(work),
               "commands": commands, "scope": "Declared RUNPATH/NEEDED/SONAME edits on generated x86_64 ELF files; not arbitrary-ELF relocation or an APT transaction."}

    def run(label: str, argv: list[str], *, missing_library: str | None = None) -> str:
        result = subprocess.run(argv, cwd=work, env=environment, capture_output=True, text=True, timeout=30)
        stem = f"{len(commands) + 1:02d}-{label}"
        stdout, stderr = work / (stem + ".stdout"), work / (stem + ".stderr")
        stdout.write_text(result.stdout); stderr.write_text(result.stderr)
        commands.append({"argv": argv, "cwd": str(work), "returncode": result.returncode,
                         "expected": "missing-library failure" if missing_library else "exit 0", "stdout": str(stdout), "stderr": str(stderr),
                         "stdout_sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
                         "stderr_sha256": hashlib.sha256(stderr.read_bytes()).hexdigest()})
        if missing_library is not None:
            require(result.returncode != 0 and missing_library in result.stderr,
                    "Expected a dynamic-loader failure identifying " + missing_library)
        else:
            require(result.returncode == 0, label + " failed with exit " + str(result.returncode) + ": " + result.stderr[-2000:])
        return result.stdout

    try:
        version = run("version", [str(tool), "--version"]).strip()
        require(version == "patchelf " + expected_version, "Unexpected patchelf version: " + version)
        summary["version"] = version
        library_source, main_source = work / "library.c", work / "main.c"
        library_source.write_text("int cpg_value(void) { return 42; }\n")
        main_source.write_text('#include <stdio.h>\nint cpg_value(void);\nint main(void) { int n = cpg_value(); printf("%d\\n", n); return n != 42; }\n')
        original = work / "original"
        (original / "bin").mkdir(parents=True)
        (original / "lib").mkdir()
        library, program = original / "lib" / OLD_LIBRARY, original / "bin/program"
        run("compile-library", [cc, "-shared", "-fPIC", "-Wl,-soname," + OLD_LIBRARY, str(library_source), "-o", str(library)])
        run("compile-program", [cc, str(main_source), "-L" + str(original / "lib"), "-lcpg_elf_probe",
                                "-Wl,-rpath," + str(work / "deliberately-missing"), "-o", str(program)])
        require(program.read_bytes()[:4] == b"\x7fELF", "Compiler did not produce an ELF executable")
        initial_needed = needed(run("initial-needed", [str(tool), "--print-needed", str(program)]))
        require(OLD_LIBRARY in initial_needed, "The test program did not record its shared library dependency")
        run("missing-runpath", [str(program)], missing_library=OLD_LIBRARY)
        run("set-runpath", [str(tool), "--set-rpath", RUNPATH, str(program)])
        require(run("read-runpath", [str(tool), "--print-rpath", str(program)]).strip() == RUNPATH,
                "Patched origin-relative RUNPATH differs")
        require(run("execute-patched", [str(program)]).strip() == "42", "RUNPATH edit changed program output")
        relocated = work / "relocated"
        original.rename(relocated)
        require(not original.exists(), "The original tree must be absent during relocation validation")
        program, library = relocated / "bin/program", relocated / "lib" / OLD_LIBRARY
        require(run("execute-relocated", [str(program)]).strip() == "42", "Origin-relative RUNPATH did not survive relocation")
        run("replace-needed", [str(tool), "--replace-needed", OLD_LIBRARY, NEW_LIBRARY, str(program)])
        changed_needed = needed(run("changed-needed", [str(tool), "--print-needed", str(program)]))
        require(NEW_LIBRARY in changed_needed and OLD_LIBRARY not in changed_needed, "DT_NEEDED replacement differs")
        run("missing-renamed-library", [str(program)], missing_library=NEW_LIBRARY)
        renamed = library.with_name(NEW_LIBRARY)
        library.rename(renamed)
        require(run("execute-renamed-needed", [str(program)]).strip() == "42", "DT_NEEDED replacement did not load the renamed library")
        run("set-soname", [str(tool), "--set-soname", NEW_LIBRARY, str(renamed)])
        require(run("read-soname", [str(tool), "--print-soname", str(renamed)]).strip() == NEW_LIBRARY, "Library SONAME differs")
        require(run("execute-renamed-soname", [str(program)]).strip() == "42", "SONAME edit changed executable behavior")
        summary.update(status="passed", runpath=RUNPATH, needed_before=sorted(initial_needed), needed_after=sorted(changed_needed),
                       negative_loader_checks=2, successful_execution_variants=4,
                       program_sha256=hashlib.sha256(program.read_bytes()).hexdigest(),
                       library_sha256=hashlib.sha256(renamed.read_bytes()).hexdigest(),
                       operations=["version", "missing-library failure", "origin-relative RUNPATH", "moved tree execution",
                                   "DT_NEEDED replacement and execution", "SONAME replacement and execution"])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        summary.update(status="failed", reason=str(error))
    (work / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", type=Path, default=Path("/usr/bin/patchelf"))
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--expected-version", default="0.18.0")
    args = parser.parse_args()
    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="patchelf-", dir=args.work_dir)).resolve()
    result = qualify(args.tool, work, cc=args.cc, expected_version=args.expected_version)
    print(json.dumps({key: value for key, value in result.items() if key != "commands"}, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
