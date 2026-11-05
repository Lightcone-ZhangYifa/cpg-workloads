#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise ASCII, UTF BOM and incremental encoding detection."""
    ascii_data = b"compiler playground 123\n" * 30
    first = module.detect(ascii_data)
    require(first["encoding"].lower() == "ascii" and first["confidence"] > 0.9, "ASCII detection failed")
    text = "Compiler 北京师范大学 café" * 10
    utf = text.encode("utf-8-sig")
    detected = module.detect(utf)
    require(utf.decode(detected["encoding"]) == text, "BOM UTF roundtrip failed")
    universal = installed_module("chardet.universaldetector")
    detector = universal.UniversalDetector()
    for start in range(0, len(utf), 11): detector.feed(utf[start:start+11])
    detector.close()
    require(utf.decode(detector.result["encoding"]) == text, "Incremental detection failed")
    require(module.detect(b"")["encoding"] == "utf-8", "Documented default empty input handling failed")
    require(module.detect(b"", empty_input_encoding="ascii")["encoding"] == "ascii", "Explicit empty input policy failed")
    raises(TypeError, lambda: module.detect("text rather than bytes"), "Non-byte input accepted")
    return {"checks": ["ascii-detection", "utf8-bom-roundtrip", "incremental-detection", "default-empty-input", "explicit-empty-input-policy", "invalid-type"]}

if __name__ == "__main__":
    raise SystemExit(main('chardet', 'chardet', functional))
