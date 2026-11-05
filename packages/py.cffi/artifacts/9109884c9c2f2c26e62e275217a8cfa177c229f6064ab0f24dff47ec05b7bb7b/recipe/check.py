#!/usr/bin/env python3
"""Installed functional check for cffi; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(cffi, work):
    """Exercise the installed extension without compiling or loading a custom library."""
    installed_module("_cffi_backend")
    ffi = cffi.FFI()
    ffi.cdef("size_t strlen(const char *s); int memcmp(const void *, const void *, size_t);")
    libc = ffi.dlopen(None)
    buffer = ffi.new("char[]", b"compiler")
    require(libc.strlen(buffer) == 8, "C strlen result mismatch")
    require(ffi.string(buffer) == b"compiler", "C buffer mismatch")
    callback = ffi.callback("int(int)", lambda n: n+3)
    require(callback(7) == 10, "C callback mismatch")
    require(libc.memcmp(buffer, b"compiler", 8) == 0, "C memcmp result mismatch")
    raises(IndexError, lambda: buffer[100], "Out-of-bounds C array access was accepted")
    raises(cffi.CDefError, lambda: ffi.cdef("not a C declaration !!!"), "Invalid declaration was accepted")
    return {"checks": ["extension-location", "libc-abi", "native-buffer", "callback", "array-bounds", "invalid-cdef"], "out_of_line_compilation": "not_run"}

if __name__ == "__main__":
    raise SystemExit(main('cffi', 'cffi', functional))
