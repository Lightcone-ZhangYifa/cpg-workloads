#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise Unicode hostname encoding, roundtrip and invalid labels."""
    names = ["bücher.example", "例子.测试"]
    for name in names:
        encoded = module.encode(name)
        require(encoded.isascii() and module.decode(encoded) == name, "IDNA roundtrip failed")
    require(module.encode("bücher.example") == b"xn--bcher-kva.example", "Known punycode mismatch")
    require(module.encode("EXAMPLE.COM", uts46=True) == b"example.com", "UTS46 case mapping failed")
    for name in ["bad name.example", "a" * 64 + ".example", "a..example"]:
        raises(module.IDNAError, lambda name=name: module.encode(name), "Invalid IDNA name accepted")
    raises(module.IDNAError, lambda: module.decode(b"xn--.example"), "Invalid ACE label accepted")
    return {"checks": ["unicode-roundtrip", "known-punycode", "uts46-case-mapping", "space-rejection", "long-label-rejection", "empty-label-rejection", "invalid-ace"]}

if __name__ == "__main__":
    raise SystemExit(main('idna', 'idna', functional))
