#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Convert explicit text and bytes and exercise compatibility iterator helpers.'
    require(module.ensure_binary("雪", encoding="utf-8") == "雪".encode(), "Unicode bytes conversion failed")
    require(module.ensure_text(b"hello") == "hello" and module.ensure_str("text") == "text", "Text normalization failed")
    require(list(module.iteritems({"a": 7})) == [("a", 7)], "Compatibility iterator failed")
    require(list(module.moves.range(3)) == [0, 1, 2], "Moved range failed")
    raises(TypeError, lambda: module.ensure_binary(17), "Non-string input accepted")
    raises(UnicodeDecodeError, lambda: module.ensure_text(b"\xff", encoding="utf-8"), "Invalid UTF-8 accepted")
    return {"checks": ["unicode-binary", "text-normalization", "mapping-iterator", "moved-range", "invalid-input-type", "invalid-utf8"]}

if __name__ == '__main__':
    raise SystemExit(main('six', 'six', functional))
