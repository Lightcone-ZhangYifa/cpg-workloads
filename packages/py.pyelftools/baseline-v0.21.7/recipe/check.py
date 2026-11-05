#!/usr/bin/env python3
"""Exercise ELF symbols and DWARF using this environment's pyelftools."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


SOURCE = """#include <stdio.h>
__attribute__((noinline)) int cpg_resource_probe(int x) {
    return x * 7 + 3;
}
int main(void) {
    int value = cpg_resource_probe(5);
    printf("%d\\n", value);
    return value == 38 ? 0 : 1;
}
"""


def require_version(actual, expected):
    if actual != expected:
        raise ValueError(f"Expected pyelftools {expected}, observed {actual}")


def inspect_elf(path):
    from elftools.elf.elffile import ELFFile

    with Path(path).open("rb") as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 64 or elf["e_machine"] != "EM_X86_64":
            raise ValueError("The fixture must be an x86-64 ELF")
        text = elf.get_section_by_name(".text")
        symbols = elf.get_section_by_name(".symtab")
        if text is None or not text.data() or symbols is None:
            raise ValueError("Code or static symbol table is missing")
        matches = symbols.get_symbol_by_name("cpg_resource_probe") or []
        if len(matches) != 1 or matches[0]["st_info"]["type"] != "STT_FUNC":
            raise ValueError("Expected exactly one named function symbol")
        symbol = matches[0]
        address = int(symbol["st_value"])
        if address <= 0 or int(symbol["st_size"]) <= 0 or not elf.has_dwarf_info():
            raise ValueError("Function extent or DWARF information is missing")
        dwarf = elf.get_dwarf_info()
        functions, source_lines = [], []
        for unit in dwarf.iter_CUs():
            for die in unit.iter_DIEs():
                attribute = die.attributes.get("DW_AT_name")
                if die.tag == "DW_TAG_subprogram" and attribute is not None and attribute.value == b"cpg_resource_probe":
                    functions.append(die)
            lines = dwarf.line_program_for_CU(unit)
            if lines is not None:
                for entry in lines.get_entries():
                    if entry.state is not None and not entry.state.end_sequence and entry.state.address == address:
                        source_lines.append(entry.state.line)
        declaration_line = SOURCE.splitlines().index("__attribute__((noinline)) int cpg_resource_probe(int x) {") + 1
        if len(functions) != 1 or functions[0].attributes["DW_AT_decl_line"].value != declaration_line:
            raise ValueError("DWARF did not identify the expected function declaration")
        if declaration_line not in source_lines:
            raise ValueError("DWARF line information did not map the function address to its source line")
        return {"machine": elf["e_machine"], "elf_class": elf.elfclass,
                "text_bytes": len(text.data()), "symbol": symbol.name,
                "symbol_address": address, "symbol_size": int(symbol["st_size"]),
                "source_line": declaration_line, "line_table_matches": source_lines}


def qualify(expected_version="0.33"):
    version = importlib.metadata.version("pyelftools")
    require_version(version, expected_version)
    compiler = shutil.which("cc")
    if compiler is None:
        raise ValueError("A C compiler named cc is required for this check")
    commands = []

    def run(argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                                env=dict(os.environ, LC_ALL="C"), check=False)
        commands.append({"argv": argv, "returncode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != 0:
            raise ValueError("Fixture command failed: " + repr(argv))
        return result

    with tempfile.TemporaryDirectory(prefix="cpg-pyelftools-") as directory:
        directory = Path(directory)
        source, executable = directory / "probe.c", directory / "probe"
        source.write_text(SOURCE)
        run([compiler, "-std=c11", "-g", "-O0", "-fno-pie", "-no-pie", str(source), "-o", str(executable)])
        if run([str(executable)]).stdout != "38\n":
            raise ValueError("Compiled fixture returned unexpected output")
        decoded = inspect_elf(executable)
        stripped = directory / "without-debug"
        run([compiler, "-std=c11", "-O0", "-g0", "-s", "-fno-pie", "-no-pie", str(source), "-o", str(stripped)])
        try:
            inspect_elf(stripped)
        except ValueError:
            negative = "passed: missing symbols/debug data were rejected"
        else:
            raise ValueError("The negative control was incorrectly accepted")
    return {"status": "passed", "check": "elf-symbols-dwarf-lines", "version": version,
            "decoded": decoded, "negative_control": negative, "commands": commands,
            "scope": "Native x86-64 ELF and DWARF from the recorded C compiler; not all object/debug formats."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default="0.33")
    args = parser.parse_args()
    try:
        result = qualify(args.expected_version)
    except (OSError, ValueError, KeyError, ImportError, importlib.metadata.PackageNotFoundError,
            subprocess.SubprocessError) as error:
        result = {"status": "failed", "check": "elf-symbols-dwarf-lines", "reason": str(error)}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
