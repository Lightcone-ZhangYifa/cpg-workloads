#!/usr/bin/env python3
"""Future libdislocator allocation/guard-page check; does not qualify AFL network tools."""
import argparse
import ast
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


CHILD = r'''
import ctypes, os, resource, sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
library = ctypes.CDLL(sys.argv[1], mode=os.RTLD_LOCAL | os.RTLD_NOW)
library.malloc.argtypes = [ctypes.c_size_t]
library.malloc.restype = ctypes.c_void_p
library.free.argtypes = [ctypes.c_void_p]
library.free.restype = None
pointer = library.malloc(32)
if not pointer:
    raise RuntimeError("Packaged allocator returned a null pointer")
ctypes.memset(pointer, 0xA5, 32)
if ctypes.string_at(pointer, 32) != bytes([0xA5]) * 32:
    raise RuntimeError("Allocated bytes cannot be read back exactly")
print("allocation-and-readback-ok", flush=True)
if sys.argv[2] == "overflow":
    ctypes.c_ubyte.from_address(pointer + 32).value = 0x5A
    raise RuntimeError("The protected boundary accepted an out-of-bounds write")
library.free(pointer)
print("free-ok", flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    args = parser.parse_args()
    library = args.prefix.resolve() / "lib/afl/libdislocator.so"
    if not library.is_file():
        raise RuntimeError("The declared extension library is not installed")
    # Use explicit calls into this library, never globally preload the interpreter.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("AFL_") and key != "LD_PRELOAD"}
    env["LC_ALL"] = "C"
    ast.parse(CHILD)
    with tempfile.TemporaryDirectory(prefix="cpg-afl-extension-check-") as folder:
        control = subprocess.run([sys.executable, "-B", "-c", CHILD, str(library), "control"],
                                 cwd=folder, env=env, capture_output=True, timeout=8)
        if control.returncode != 0 or control.stdout != b"allocation-and-readback-ok\nfree-ok\n":
            raise RuntimeError("Packaged libdislocator failed allocation/readback/free")
        overflow = subprocess.run([sys.executable, "-B", "-c", CHILD, str(library), "overflow"],
                                  cwd=folder, env=env, capture_output=True, timeout=8)
        if overflow.returncode != -signal.SIGSEGV or overflow.stdout != b"allocation-and-readback-ok\n":
            raise RuntimeError("Packaged libdislocator failed to trap its protected allocation boundary")
    print(json.dumps({"status": "passed", "scope": "libdislocator_allocation_and_guard_page_only",
                      "network_tools_qualified": False, "afl_core_qualified": False}))


if __name__ == "__main__":
    main()
