#!/usr/bin/env python3
"""Installed LIEF check with a self-contained ELF64 fixture and real execution."""
from pathlib import Path
import hashlib
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, main, require

def elf_fixture():
    # Linux x86-64: exit(42). One load segment and an explicit section-name table.
    code = bytes.fromhex("b8 3c 00 00 00 bf 2a 00 00 00 0f 05")
    names = b"\0.text\0.shstrtab\0"
    code_offset, names_offset, section_offset = 0x100, 0x110, 0x128
    size = section_offset + 3 * 64
    data = bytearray(size)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(8)
    data[:64] = struct.pack("<16sHHIQQQIHHHHHH", ident, 2, 62, 1, 0x400000 + code_offset,
                            64, section_offset, 0, 64, 56, 1, 64, 3, 2)
    data[64:120] = struct.pack("<IIQQQQQQ", 1, 5, 0, 0x400000, 0x400000, size, size, 0x1000)
    data[code_offset:code_offset + len(code)] = code
    data[names_offset:names_offset + len(names)] = names
    data[section_offset + 64:section_offset + 128] = struct.pack("<IIQQQQIIQQ", 1, 1, 6,
             0x400000 + code_offset, code_offset, len(code), 0, 0, 16, 0)
    data[section_offset + 128:section_offset + 192] = struct.pack("<IIQQQQIIQQ", 7, 3, 0,
             0, names_offset, len(names), 0, 0, 1, 0)
    return bytes(data), code

def functional(lief, work):
    """Parse an exact ELF, rename a section, rewrite and execute both copies."""
    raw, code = elf_fixture()
    original = work / "fixture.elf"; original.write_bytes(raw); original.chmod(0o755)
    binary = lief.ELF.parse(str(original))
    require(binary is not None and binary.entrypoint == 0x400100, "Wrong ELF entrypoint")
    require(int(binary.header.machine_type) == 62 and int(binary.header.file_type) == 2, "Wrong ELF target")
    require(len(binary.segments) == 1 and len(binary.sections) == 3, "Wrong ELF layout")
    text = binary.get_section(".text")
    require(text is not None and bytes(text.content) == code, "Wrong ELF code bytes")
    child([original], expected=42)
    text.name = ".code"
    rewritten = work / "rewritten.elf"; binary.write(str(rewritten)); rewritten.chmod(0o755)
    reparsed = lief.ELF.parse(str(rewritten))
    require(reparsed is not None and reparsed.entrypoint == 0x400100, "Rewritten ELF entrypoint changed")
    require(reparsed.get_section(".text") is None and bytes(reparsed.get_section(".code").content) == code,
            "Section rename or byte preservation failed")
    child([rewritten], expected=42)
    invalid = work / "invalid.bin"; invalid.write_bytes(b"not an executable\x00")
    require(lief.parse(str(invalid)) is None, "Invalid executable accepted")
    return {"checks": ["deterministic-elf64-parse", "header-segment-section-values", "exact-code-bytes",
                       "original-execution", "section-rename-and-write", "rewritten-execution", "invalid-format"],
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "rewritten_sha256": hashlib.sha256(rewritten.read_bytes()).hexdigest(),
            "scope": "Linux x86-64 ELF parsing and rewriting; PE/Mach-O and other targets not exercised"}

if __name__ == "__main__":
    raise SystemExit(main("lief", "lief", functional))
