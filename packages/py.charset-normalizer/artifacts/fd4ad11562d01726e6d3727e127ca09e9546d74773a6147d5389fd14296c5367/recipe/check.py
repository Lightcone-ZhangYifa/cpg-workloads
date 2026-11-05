#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise byte decoding, BOM handling, files and invalid input."""
    text = "Compiler 北京师范大学 café\n" * 20
    encoded = text.encode("utf-8")
    match = module.from_bytes(encoded).best()
    require(match is not None and str(match) == text, "UTF-8 text reconstruction failed")
    ascii_match = module.from_bytes(b"compiler playground 123").best()
    require(ascii_match is not None and str(ascii_match) == "compiler playground 123", "ASCII reconstruction failed")
    utf16 = module.from_bytes(text.encode("utf-16")).best()
    require(utf16 is not None and str(utf16) == text, "UTF-16 BOM reconstruction failed")
    fixture = work / "text.bin"; fixture.write_bytes(encoded)
    require(str(module.from_path(fixture).best()) == text, "Path decoding failed")
    raises(TypeError, lambda: module.from_bytes(text), "Unicode input accepted by bytes API")
    return {"checks": ["utf8-reconstruction", "ascii-reconstruction", "utf16-bom", "path-decoding", "invalid-type"]}

if __name__ == "__main__":
    raise SystemExit(main('charset-normalizer', 'charset_normalizer', functional))
