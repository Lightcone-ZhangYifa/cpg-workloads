#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Convert CSS color representations and reject invalid values.'
    require(module.name_to_hex("navy") == "#000080", "Named color lookup failed")
    rgb = module.hex_to_rgb("#1a2b3c")
    require(tuple(rgb) == (26, 43, 60) and module.rgb_to_hex(rgb) == "#1a2b3c", "RGB/hex roundtrip failed")
    require(module.normalize_hex("#AbC") == "#aabbcc", "Short hex normalization failed")
    raises(ValueError, lambda: module.name_to_hex("cpg-no-such-color"), "Unknown color accepted")
    raises(ValueError, lambda: module.hex_to_rgb("#xyzxyz"), "Invalid hex color accepted")
    return {"checks": ["named-color", "rgb-hex-roundtrip", "short-hex-normalization", "unknown-name", "invalid-hex"]}

if __name__ == '__main__':
    raise SystemExit(main('webcolors', 'webcolors', functional))
