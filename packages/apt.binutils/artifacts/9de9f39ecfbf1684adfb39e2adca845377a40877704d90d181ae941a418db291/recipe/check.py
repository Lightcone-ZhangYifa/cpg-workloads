#!/usr/bin/env python3
"""Exercise GNU ELF tools on a real compiled program and retain command evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

TOOLS = ("readelf", "nm", "objdump", "addr2line", "ar", "objcopy", "as", "ld")
SIBLING_LIBRARY = re.compile(r"^lib(?:bfd|opcodes|ctf|sframe|gprofng)(?:[-.]|$)")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sections(text: str) -> set[str]:
    return set(re.findall(r"\[\s*\d+\]\s+(\S+)", text))


def symbol_address(text: str, name: str) -> str:
    matches = re.findall(r"^([0-9a-fA-F]+)\s+[Tt]\s+" + re.escape(name) + r"$", text, re.MULTILINE)
    require(len(matches) == 1, "Expected one defined function symbol: " + name)
    return "0x" + matches[0]


def source_location(text: str, function: str, source: Path) -> None:
    lines = text.strip().splitlines()
    require(len(lines) == 2 and lines[0] == function, "addr2line did not identify the expected function")
    filename, separator, line = lines[1].rpartition(":")
    require(bool(separator) and line.isdigit() and int(line) > 0
            and Path(filename).resolve() == source.resolve(), "addr2line did not identify the actual source line")


def qualify(prefix: Path, work: Path, *, cc: str = "cc", expected_version: str = "2.42") -> dict:
    prefix = prefix.resolve(strict=True)
    work.mkdir(parents=True, exist_ok=True)
    commands, tools, versions, loaded = [], {}, {}, {}
    environment = dict(os.environ, LC_ALL="C", LANG="C")
    environment.pop("LD_PRELOAD", None)
    environment.pop("LD_AUDIT", None)
    environment["LD_LIBRARY_PATH"] = str(prefix / "lib/x86_64-linux-gnu")
    summary = {"status": "running", "check": "gnu-binutils-elf-roundtrip", "prefix": str(prefix),
               "work_directory": str(work), "commands": commands, "tools": tools, "versions": versions,
               "loaded_sibling_libraries": loaded, "scope": "Declared ELF operations on x86_64; not an APT transaction or full binutils qualification."}

    def run(label: str, argv: list[str], *, clean_loader: bool = False) -> str:
        chosen = dict(environment)
        if clean_loader:
            chosen.pop("LD_LIBRARY_PATH", None)
        result = subprocess.run(argv, cwd=work, env=chosen, capture_output=True, text=True, timeout=30)
        stem = f"{len(commands) + 1:02d}-{label}"
        stdout, stderr = work / (stem + ".stdout"), work / (stem + ".stderr")
        stdout.write_text(result.stdout); stderr.write_text(result.stderr)
        commands.append({"argv": argv, "cwd": str(work), "returncode": result.returncode,
                         "stdout": str(stdout), "stderr": str(stderr), "loader_library_path": chosen.get("LD_LIBRARY_PATH"),
                         "stdout_sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
                         "stderr_sha256": hashlib.sha256(stderr.read_bytes()).hexdigest()})
        require(result.returncode == 0, label + " failed with exit " + str(result.returncode) + ": " + result.stderr[-2000:])
        return result.stdout

    try:
        for name in TOOLS:
            executable = (prefix / "bin" / name).resolve(strict=True)
            require(executable.is_file() and executable.is_relative_to(prefix), "Tool resolves outside its declared prefix: " + name)
            tools[name] = {"path": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
            output = run("version-" + name, [str(executable), "--version"])
            first = output.splitlines()[0] if output.splitlines() else ""
            require("GNU" in first and re.search(r"\b" + re.escape(expected_version) + r"(?:\s|$)", first) is not None,
                    "Unexpected GNU tool version: " + first)
            versions[name] = first
            listing = run("loader-" + name, ["/lib64/ld-linux-x86-64.so.2", "--list", str(executable)])
            loaded[name] = {}
            for line in listing.splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and parts[1] == "=>" and SIBLING_LIBRARY.match(parts[0]):
                    library = Path(parts[2]).resolve(strict=True)
                    require(library.is_relative_to(prefix), "A binutils sibling library was loaded from another installation: " + str(library))
                    loaded[name][parts[0]] = {"path": str(library), "sha256": hashlib.sha256(library.read_bytes()).hexdigest()}
        require(any(loaded.values()), "No binutils sibling library binding was observed")
        binary = lambda name: tools[name]["path"]
        library_source, main_source = work / "library.c", work / "main.c"
        library_source.write_text("__attribute__((noinline)) int cpg_answer(int value) {\n    return value * 2 + 2;\n}\n")
        main_source.write_text('#include <stdio.h>\nint cpg_answer(int);\nint main(void) { int n = cpg_answer(20); printf("%d\\n", n); return n != 42; }\n')
        library_object, main_object = work / "library.o", work / "main.o"
        compiler = [cc, "-B" + str(prefix / "bin") + "/", "-g", "-O0", "-fno-pie", "-fno-inline"]
        run("compile-library", [*compiler, "-c", str(library_source), "-o", str(library_object)])
        run("compile-main", [*compiler, "-c", str(main_source), "-o", str(main_object)])
        first_archive, second_archive = work / "libanswer.a", work / "libanswer-repeat.a"
        run("archive-first", [binary("ar"), "rcsD", str(first_archive), str(library_object)])
        os.utime(library_object, (946684800, 946684800))
        run("archive-repeat", [binary("ar"), "rcsD", str(second_archive), str(library_object)])
        require(first_archive.read_bytes() == second_archive.read_bytes(), "Deterministic ar output changed with member mtime")
        require(run("archive-list", [binary("ar"), "t", str(first_archive)]).strip() == "library.o", "Archive member list differs")
        program = work / "program"
        run("link", [cc, "-B" + str(prefix / "bin") + "/", "-no-pie", str(main_object), str(first_archive), "-o", str(program)])
        require(run("execute", [str(program)], clean_loader=True).strip() == "42", "Compiled program returned wrong output")
        header = run("elf-header", [binary("readelf"), "-h", str(program)])
        require("ELF64" in header and "X86-64" in header, "Unexpected ELF class or machine")
        section_text = run("elf-sections", [binary("readelf"), "-SW", str(program)])
        require({".text", ".debug_info", ".debug_line"}.issubset(sections(section_text)), "Required code or debug sections are missing")
        relocation = run("elf-relocations", [binary("readelf"), "-rW", str(main_object)])
        require("cpg_answer" in relocation and "R_X86_64" in relocation, "Expected function relocation is missing")
        address = symbol_address(run("symbols", [binary("nm"), "-n", "--defined-only", str(program)]), "cpg_answer")
        disassembly = run("disassembly", [binary("objdump"), "-d", "--disassemble=cpg_answer", str(program)])
        require("<cpg_answer>:" in disassembly and re.search(r"\bret[q]?\b", disassembly) is not None, "Function disassembly is incomplete")
        source_location(run("source-line", [binary("addr2line"), "-e", str(program), "-f", address]), "cpg_answer", library_source)
        debug, stripped, text = work / "program.debug", work / "program.stripped", work / "text.bin"
        run("split-debug", [binary("objcopy"), "--only-keep-debug", str(program), str(debug)])
        run("strip-debug", [binary("objcopy"), "--strip-debug", str(program), str(stripped)])
        run("debug-link", [binary("objcopy"), "--add-gnu-debuglink=" + str(debug), str(stripped)])
        stripped_sections = sections(run("stripped-sections", [binary("readelf"), "-SW", str(stripped)]))
        require(".gnu_debuglink" in stripped_sections and ".debug_info" not in stripped_sections, "Split debug metadata was not installed correctly")
        source_location(run("linked-debug-line", [binary("addr2line"), "-e", str(stripped), "-f", address]), "cpg_answer", library_source)
        require(run("execute-stripped", [str(stripped)], clean_loader=True).strip() == "42", "Debug processing changed executable behavior")
        run("dump-code", [binary("objcopy"), "--dump-section", ".text=" + str(text), str(program)])
        require(text.is_file() and text.stat().st_size > 0, "objcopy did not extract code bytes")
        summary.update(status="passed", function_address=address, deterministic_archive_sha256=hashlib.sha256(first_archive.read_bytes()).hexdigest(),
                       code_section_bytes=text.stat().st_size, operations=["ELF headers/sections/relocations", "defined symbols", "function disassembly",
                       "address-to-source mapping", "deterministic static archive", "assembler/linker execution", "split debug and debuglink resolution", "section extraction"])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        summary.update(status="failed", reason=str(error))
    (work / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path("/usr"))
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--expected-version", default="2.42")
    args = parser.parse_args()
    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="binutils-", dir=args.work_dir)).resolve()
    result = qualify(args.prefix, work, cc=args.cc, expected_version=args.expected_version)
    print(json.dumps({key: value for key, value in result.items() if key not in {"commands", "tools", "loaded_sibling_libraries"}}, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
