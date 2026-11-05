#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Parse, format and percent-transform URLs without double encoding.'
    url = "https://example.com:8443/path?q=hello#part"
    parsed = module.parse(url)
    require(parsed.hostname == "example.com" and parsed.port == "8443", "URL authority parse failed")
    require(parsed.pathname == "/path" and parsed.search == "?q=hello", "URL path/query parse failed")
    require(module.format(parsed) == url, "URL format roundtrip failed")
    text = "snow ☃ and space"
    encoded = module.encode(text)
    require("%20" in encoded and "%E2%98%83" in encoded, "UTF-8 percent encoding failed")
    require(module.decode(encoded) == text, "UTF-8 percent decoding failed")
    require(module.encode(encoded) == encoded, "Already encoded URL was encoded twice")
    require(module.decode("bad%ZZ") == "bad%ZZ", "Invalid percent escape policy changed")
    return {"checks": ["authority-parse", "path-query-parse", "format-roundtrip", "utf8-percent-roundtrip", "double-encoding-avoidance", "invalid-percent-input"]}

if __name__ == '__main__':
    raise SystemExit(main('mdurl', 'mdurl', functional))
