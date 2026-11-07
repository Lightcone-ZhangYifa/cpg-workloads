#!/usr/bin/env python3
"""Bounded executable tests for worker022; every command and result is retained."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time


class Run:
    def __init__(self, output: Path):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.commands = []
        self.assertions = []

    def cmd(self, args, *, cwd=None, expect=0):
        args = [str(x) for x in args]
        start = time.monotonic()
        p = subprocess.run(args, cwd=cwd or self.output, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        row = dict(argv=args, cwd=str(cwd or self.output), returncode=p.returncode,
                   stdout=p.stdout, stderr=p.stderr, elapsed_seconds=time.monotonic()-start)
        self.commands.append(row)
        if expect == "nonzero":
            self.check(p.returncode != 0, "reject invalid input: " + args[0])
        else:
            self.check(p.returncode == expect, "command return code: " + args[0])
        return p.stdout + p.stderr

    def check(self, condition, description):
        self.assertions.append(dict(description=description, passed=bool(condition)))
        if not condition:
            self.save("failed")
            raise AssertionError(description)

    def file(self, name, text):
        p = self.output/name
        p.write_text(text)
        return p

    def save(self, status="passed", **extra):
        data = dict(status=status, commands=self.commands, assertions=self.assertions,
                    assertion_count=len(self.assertions), **extra)
        (self.output/"result.json").write_text(json.dumps(data, indent=2)+"\n")
        return data


def native(r, linker):
    driver = r.output/"linker-driver"
    driver.mkdir(exist_ok=True)
    if not (driver/"ld").exists():
        (driver/"ld").symlink_to(linker.resolve())
    r.check((driver/"ld").resolve() == linker.resolve(), "explicit linker driver binding")
    options = ["-B"+str(driver)]
    r.file("calc.c", "long calc(int n) { long v=7; for(int i=0;i<n;i++) v+=(long)i*i+3; return v; }\nlong unused(void) { return 123456; }\n")
    r.file("main.c", '#include <stdio.h>\n#include <stdlib.h>\nextern long calc(int);\n_Thread_local long tls=11;\nint main(int argc,char **argv) { int n=argc>1?atoi(argv[1]):10; printf("%ld,%ld\\n",calc(n),tls); return 0; }\n')
    r.cmd(["gcc", "-O2", "-ffunction-sections", "-fdata-sections", "-c", "calc.c"])
    r.cmd(["gcc", "-O2", "-ffunction-sections", "-fdata-sections", "-c", "main.c"])
    r.cmd(["ar", "rcs", "libcalc.a", "calc.o"])
    r.cmd(["gcc", "main.o", "libcalc.a", "-Wl,--gc-sections", "-o", "reference"])
    r.cmd(["gcc", *options, "main.o", "libcalc.a", "-Wl,--gc-sections", "-o", "candidate"])
    for n in [-1, 0, 1, 10, 33, 127]:
        expected = str(7+sum(i*i+3 for i in range(max(0, n))))+",11\n"
        ref = r.cmd([r.output/"reference", str(n)])
        got = r.cmd([r.output/"candidate", str(n)])
        r.check(ref == got == expected, f"independent arithmetic oracle n={n}")
    info = r.cmd(["readelf", "-h", "candidate"])
    r.check("ELF64" in info and "X86-64" in info, "native ELF64 x86-64 output")
    symbols = r.cmd(["readelf", "-sW", "candidate"])
    r.check("unused" not in symbols, "unreferenced function removed by section GC")
    r.cmd(["gcc", "-fPIC", "-O2", "-c", "calc.c", "-o", "calc-pic.o"])
    r.cmd(["gcc", *options, "-shared", "calc-pic.o", "-Wl,-soname,libcalc.so", "-o", "libcalc.so"])
    r.cmd(["gcc", *options, "main.o", "-L.", "-lcalc", "-Wl,-rpath,$ORIGIN", "-o", "dynamic"])
    r.check(r.cmd([r.output/"dynamic", "10"]) == "322,11\n", "shared library and runtime search path")
    r.file("missing.c", "extern int missing_symbol(void); int main(void) {return missing_symbol();}\n")
    bad = r.cmd(["gcc", *options, "missing.c", "-o", "missing"], expect="nonzero")
    r.check("missing_symbol" in bad, "undefined-symbol diagnostic identifies the missing symbol")
    r.file("duplicate.c", "long calc(int n) { return n+99; }\n")
    r.cmd(["gcc", "-c", "duplicate.c", "-o", "different-calc.o"])
    duplicate = r.cmd(["gcc", *options, "main.o", "calc.o", "different-calc.o", "-o", "duplicate"], expect="nonzero")
    r.check("calc" in duplicate, "duplicate-definition diagnostic identifies calc")
    r.file("malformed.o", "this is deliberately not an object file\n")
    r.cmd([str(linker), "malformed.o", "-o", "bad"], expect="nonzero")
    return dict(scope="x86_64 Linux ELF: archive, GC, TLS, shared library, symbol errors",
                executable_cases=7, hardware_targets=["x86_64-linux"])


def leb(n):
    out = bytearray()
    while True:
        byte = n & 127
        n >>= 7
        out.append(byte | (128 if n else 0))
        if not n:
            return bytes(out)


def wasm_object():
    """A complete relocatable add(i32,i32)->i32 object using linking convention v2.

    No call/data relocation is required for this function. The strong function
    symbol belongs to linking subsection 8. This is not a general C compiler.
    Reference: WebAssembly/tool-conventions, Linking.md, Symbol Table Subsection.
    """
    def section(kind, body):
        return bytes([kind])+leb(len(body))+body
    symbols = bytes([1, 0, 0, 0, 3])+b"add"
    linking = leb(7)+b"linking"+leb(2)+bytes([8])+leb(len(symbols))+symbols
    return (b"\0asm\x01\0\0\0"
            + section(1, bytes([1, 0x60, 2, 0x7f, 0x7f, 1, 0x7f]))
            + section(3, bytes([1, 0]))
            + section(10, bytes([1, 7, 0, 0x20, 0, 0x20, 1, 0x6a, 0x0b]))
            + section(0, linking))


def formats(r, toolchain):
    b = toolchain/"bin"
    clang, lld, readobj = b/"clang", b/"lld", b/"llvm-readobj"
    r.check("23.1.4" in r.cmd([b/"ld.lld", "--version"]), "fixed LLD version 23.1.4")
    r.check("23.1.4" in r.cmd([clang, "--version"]), "fixed Clang version 23.1.4")
    original = r.output
    elf = Run(original/"elf")
    native(elf, b/"ld.lld")
    elf.save()
    r.check(True, "ELF executable/reference suite passed")
    r.file("coff.c", "int add(int a,int b) {return a+b;} void start(void) {}\n")
    r.cmd([clang, "--target=x86_64-pc-windows-msvc", "-ffreestanding", "-c", "coff.c", "-o", "coff.obj"])
    r.cmd([lld, "-flavor", "link", "/entry:start", "/subsystem:console", "/nodefaultlib", "/export:add", "/out:coff.exe", "coff.obj"])
    headers = r.cmd([readobj, "--file-headers", "--coff-exports", "coff.exe"])
    r.check("IMAGE_FILE_MACHINE_AMD64" in headers and "Name: add" in headers, "PE/COFF x64 executable headers and export")
    r.file("macho.c", "int add(int a,int b) {return a+b;} int main(void) {return add(19,23);}\n")
    r.cmd([clang, "--target=x86_64-apple-darwin", "-ffreestanding", "-fno-stack-protector", "-c", "macho.c", "-o", "macho.o"])
    r.cmd([lld, "-flavor", "darwin", "-arch", "x86_64", "-platform_version", "macos", "11.0", "11.0", "-e", "_main", "macho.o", "-o", "macho.exe"])
    headers = r.cmd([readobj, "--file-headers", "--symbols", "macho.exe"])
    r.check("Mach-O" in headers and "Name: _add" in headers and "FileType: Executable (0x2)" in headers, "Mach-O x64 executable and defined add symbol")
    (r.output/"add.o").write_bytes(wasm_object())
    r.cmd([lld, "-flavor", "wasm", "--no-entry", "--export=add", "add.o", "-o", "add.wasm"])
    js = "const fs=require('fs'); WebAssembly.instantiate(fs.readFileSync(process.argv[1])).then(({instance:x})=>{for(const [a,b] of [[19,23],[0,0],[-5,9],[2147483647,1]]){const got=x.exports.add(a,b);if(got!==((a+b)|0)) throw Error('bad sum');}console.log('4 wasm execution cases passed');}).catch(e=>{console.error(e);process.exit(1)});"
    r.check("4 wasm execution cases passed" in r.cmd(["node", "-e", js, "add.wasm"]), "Wasm linked output executes four integer cases")
    for flavor, args in [("link", ["/entry:absent", "/subsystem:console", "/nodefaultlib", "coff.obj", "/out:bad.exe"]),
                         ("darwin", ["-arch", "x86_64", "-platform_version", "macos", "11.0", "11.0", "-e", "_absent", "macho.o", "-o", "bad-macho"]),
                         ("wasm", ["--no-entry", "--export=absent", "add.o", "-o", "bad.wasm"])]:
        text = r.cmd([lld, "-flavor", flavor, *args], expect="nonzero")
        r.check("absent" in text, f"{flavor} rejects missing requested symbol")
    return dict(formats={"ELF": "linked and executed", "PE/COFF": "linked and structurally checked",
                         "Mach-O": "linked and structurally checked", "Wasm": "linked and executed in Node"},
                windows_execution=None, macos_execution=None, full_llvm_source_build=False)


def mingw(r, toolchain):
    b = toolchain/"bin"
    cc, cxx, inspect = b/"x86_64-w64-mingw32-gcc", b/"x86_64-w64-mingw32-g++", b/"llvm-readobj"
    r.check("23.1.4" in r.cmd([cc, "--version"]), "fixed LLVM 23.1.4 release compiler")
    r.file("library.c", "__declspec(dllexport) int cpg_add(int a,int b) {return a+b;}\n")
    r.file("consumer.c", '#include <stdio.h>\n__declspec(dllimport) int cpg_add(int,int);\nint main(void){printf("%d\\n",cpg_add(19,23));return 0;}\n')
    r.cmd([cc, "-O2", "-shared", "library.c", "-Wl,--out-implib,libcpg.dll.a", "-o", "cpg.dll"])
    r.cmd([cc, "-O2", "consumer.c", "-L.", "-lcpg", "-o", "consumer.exe"])
    exports = r.cmd([inspect, "--file-headers", "--coff-exports", "cpg.dll"])
    imports = r.cmd([inspect, "--file-headers", "--coff-imports", "consumer.exe"])
    r.check("IMAGE_FILE_MACHINE_AMD64" in imports, "Windows x64 machine type")
    r.check("Name: cpg_add" in exports, "DLL export exists")
    r.check("Name: cpg.dll" in imports and "Symbol: cpg_add" in imports, "consumer imports expected DLL symbol")
    r.check("ucrt" in imports.lower() or "api-ms-win-crt" in imports.lower(), "UCRT runtime imports match selected release")
    r.file("cpp.cpp", '#include <vector>\n#include <stdexcept>\nint main(){try{std::vector<int> v{19,23};if(v[0]+v[1]==42)throw std::runtime_error("checked");}catch(const std::exception&){return 0;}return 1;}\n')
    r.cmd([cxx, "-O2", "cpp.cpp", "-o", "cpp.exe"])
    cpp = r.cmd([inspect, "--file-headers", "--sections", "--coff-imports", "cpp.exe"])
    r.check("IMAGE_FILE_MACHINE_AMD64" in cpp and ".pdata" in cpp, "C++ exceptions produce a PE image with unwind data")
    r.file("missing.c", "extern int missing_symbol(void);int main(void){return missing_symbol();}\n")
    diagnostic = r.cmd([cc, "missing.c", "-o", "missing.exe"], expect="nonzero")
    r.check("missing_symbol" in diagnostic, "Windows cross-link rejects undefined symbol")
    return dict(target="x86_64-w64-mingw32", host="x86_64-linux", crt="ucrt",
                capabilities=["C DLL", "DLL import library", "C consumer EXE", "C++ exception EXE", "undefined-symbol rejection"],
                windows_execution=None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["native", "lld", "mingw"])
    p.add_argument("tool", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    r = Run(a.output)
    try:
        scope = {"native": native, "lld": formats, "mingw": mingw}[a.kind](r, a.tool.resolve())
        out = r.save(**scope)
        print(json.dumps({"status": out["status"], "assertions": out["assertion_count"], **scope}, sort_keys=True))
    except Exception as exc:
        r.save("failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
