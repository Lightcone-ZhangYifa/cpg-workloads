#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Validate URI grammar and distinguish references from absolute URIs.'
    require(module.validate_rfc3986("https://example.com:8443/a%20b?q=1#part", rule="URI") is not None, "Absolute URI rejected")
    require(module.validate_rfc3986("urn:isbn:9780131103627", rule="URI") is not None, "URN rejected")
    require(module.validate_rfc3986("../relative?x=2", rule="URI_reference") is not None, "Relative reference rejected")
    require(module.validate_rfc3986("../relative?x=2", rule="URI") is None, "Relative reference accepted as absolute URI")
    for value in ["https://example.com/a b", "https://example.com/%ZZ", "https://[invalid]/"]:
        require(module.validate_rfc3986(value, rule="URI") is None, "Invalid URI accepted: " + value)
    return {"checks": ["absolute-uri", "urn", "relative-reference", "absolute-relative-distinction", "invalid-space", "invalid-percent", "invalid-ip-literal"]}

if __name__ == '__main__':
    raise SystemExit(main('rfc3986-validator', 'rfc3986_validator', functional))
