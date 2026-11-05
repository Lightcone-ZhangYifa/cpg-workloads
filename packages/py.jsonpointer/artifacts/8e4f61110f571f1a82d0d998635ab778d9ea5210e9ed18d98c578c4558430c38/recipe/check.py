#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'RFC 6901 lookup and mutation with escaped keys and explicit errors.'
    doc = {"a/b": {"~key": [7, 11]}, "plain": 3}
    require(module.resolve_pointer(doc, "/a~1b/~0key/1") == 11, "Escaped pointer lookup failed")
    module.set_pointer(doc, "/a~1b/~0key/0", 19)
    require(doc["a/b"]["~key"] == [19, 11], "Pointer mutation failed")
    require(module.resolve_pointer(doc, "/absent", default="fallback") == "fallback", "Default not returned")
    raises(module.JsonPointerException, lambda: module.resolve_pointer(doc, "/absent"), "Missing pointer was accepted")
    raises(module.JsonPointerException, lambda: module.JsonPointer("not/a/pointer"), "Invalid pointer syntax was accepted")
    return {"checks": ["escaped-key-lookup", "array-mutation", "explicit-default", "missing-pointer", "invalid-pointer"]}

if __name__ == '__main__':
    raise SystemExit(main('jsonpointer', 'jsonpointer', functional))
