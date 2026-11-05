#!/usr/bin/env python3
"""Installed functional check for xxhash; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(xx, work):
    """Check published empty-input vectors and independent streaming paths."""
    require(xx.xxh32(b"").hexdigest() == "02cc5d05", "XXH32 empty vector mismatch")
    require(xx.xxh64(b"").hexdigest() == "ef46db3751d8e999", "XXH64 empty vector mismatch")
    require(xx.xxh3_64(b"").hexdigest() == "2d06800538d394c2", "XXH3 empty vector mismatch")
    data = bytes(range(256))*31
    for factory in [xx.xxh32, xx.xxh64, xx.xxh3_64, xx.xxh3_128]:
        stream = factory(seed=17)
        for offset in range(0, len(data), 37):
            stream.update(data[offset:offset+37])
        require(stream.digest() == factory(data, seed=17).digest(), "Streaming digest mismatch")
        clone = stream.copy()
        stream.update(b"x")
        require(clone.digest() != stream.digest(), "Hash state copies were not independent")
    raises(TypeError, lambda: xx.xxh64(object()), "Non-buffer input was accepted")
    return {"checks": ["three-empty-vectors", "four-streaming-families", "independent-hash-state", "invalid-input"]}

if __name__ == "__main__":
    raise SystemExit(main('xxhash', 'xxhash', functional))
