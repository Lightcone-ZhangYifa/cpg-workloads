#!/usr/bin/env python3
"""Installed Capstone check with fixed x86-64 and AArch64 known-answer bytes."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(cs, work):
    """Disassemble known instructions, verify details and reject incomplete input."""
    engine = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64); engine.detail = True
    code = bytes.fromhex("55 48 89 e5 48 83 ec 20 b8 2a 00 00 00 c9 c3")
    rows = list(engine.disasm(code, 0x1000))
    require([x.mnemonic for x in rows] == ["push", "mov", "sub", "mov", "leave", "ret"], "Wrong x86 opcodes")
    require([x.address for x in rows] == [0x1000, 0x1001, 0x1004, 0x1008, 0x100d, 0x100e], "Wrong x86 addresses")
    require([x.size for x in rows] == [1, 3, 4, 5, 1, 1] and sum(x.size for x in rows) == len(code), "Wrong instruction boundaries")
    require(rows[3].op_str == "eax, 0x2a" and rows[3].operands[1].imm == 42, "Wrong immediate operand")
    require(rows[0].reg_name(rows[0].operands[0].reg) == "rbp", "Wrong register detail")
    lite = list(engine.disasm_lite(code, 0x1000))
    require(lite == [(x.address, x.size, x.mnemonic, x.op_str) for x in rows], "Lite disassembly disagrees")
    arm = cs.Cs(cs.CS_ARCH_ARM64, cs.CS_MODE_ARM)
    arm_rows = list(arm.disasm(bytes.fromhex("20 00 80 d2 c0 03 5f d6"), 0x2000))
    require([x.mnemonic for x in arm_rows] == ["mov", "ret"] and arm_rows[0].op_str == "x0, #1", "Wrong AArch64 known answer")
    require(list(engine.disasm(bytes.fromhex("b8 01"), 0)) == [], "Truncated x86 instruction accepted")
    raises(cs.CsError, lambda: cs.Cs(65535, cs.CS_MODE_64), "Invalid architecture accepted")
    return {"checks": ["x86-known-opcodes", "addresses-and-boundaries", "register-and-immediate-details",
                       "lite-api-agreement", "aarch64-known-opcodes", "truncated-instruction", "invalid-architecture"],
            "x86_instructions": len(rows), "aarch64_instructions": len(arm_rows)}

if __name__ == "__main__":
    raise SystemExit(main("capstone", "capstone", functional))
