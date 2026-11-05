#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise comments, unquoted keys, trailing commas and rejected syntax."""
    source = "{ // comment\n unquoted: 'text', count: 0x10, values: [1, 2,], }"
    value = module.loads(source)
    require(value == {"unquoted": "text", "count": 16, "values": [1, 2]}, "JSON5 syntax parsing failed")
    require(module.loads(module.dumps(value, quote_keys=True)) == value, "JSON5 serialization roundtrip failed")
    fixture = work / "data.json5"
    with fixture.open("w") as stream: module.dump(value, stream)
    with fixture.open() as stream: require(module.load(stream) == value, "JSON5 stream roundtrip failed")
    raises(ValueError, lambda: module.loads("{broken:"), "Malformed syntax accepted")
    raises(ValueError, lambda: module.loads("{x: 1, x: 2}", allow_duplicate_keys=False), "Prohibited duplicate keys accepted")
    raises(ValueError, lambda: module.loads("{} trailing"), "Trailing content accepted")
    return {"checks": ["comments-unquoted-single-quotes", "hex-number", "trailing-comma", "serialization", "stream-roundtrip", "malformed-syntax", "duplicate-key-policy", "trailing-content"]}

if __name__ == "__main__":
    raise SystemExit(main('json5', 'json5', functional))
