#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Apply WHATWG label aliases and byte-order-mark-aware decoding.'
    require(module.lookup("  UTF8 ").name == "utf-8", "Encoding alias/whitespace lookup failed")
    require(module.lookup("latin1").name == "windows-1252", "WHATWG legacy label mapping failed")
    text = "snow 雪"
    encoded = module.encode(text, "utf-8")
    decoded, encoding = module.decode(encoded, "utf-8")
    require(decoded == text and encoding.name == "utf-8", "UTF-8 roundtrip failed")
    bom_text, bom_encoding = module.decode(b"\xef\xbb\xbfhello", "windows-1252")
    require(bom_text == "hello" and bom_encoding.name == "utf-8", "BOM precedence failed")
    require(module.lookup("cpg-unknown-encoding") is None, "Unknown label accepted")
    raises(UnicodeEncodeError, lambda: module.encode("雪", "windows-1252", errors="strict"), "Unrepresentable text was accepted")
    return {"checks": ["label-alias", "whatwg-latin1-mapping", "utf8-roundtrip", "bom-precedence", "unknown-label", "strict-encoding-error"]}

if __name__ == '__main__':
    raise SystemExit(main('webencodings', 'webencodings', functional))
