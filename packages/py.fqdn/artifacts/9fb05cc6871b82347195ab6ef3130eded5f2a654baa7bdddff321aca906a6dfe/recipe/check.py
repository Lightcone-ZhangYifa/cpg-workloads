#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Validate domain labels and absolute/relative name conversion locally."""
    domain = module.FQDN("www.example.org")
    require(domain.is_valid and domain.relative == "www.example.org" and domain.absolute == "www.example.org.", "Domain conversion failed")
    absolute = module.FQDN("www.example.org.")
    require(absolute.is_valid and absolute.relative == domain.relative, "Absolute domain failed")
    raises(ValueError, lambda: module.FQDN(""), "Empty domain accepted")
    invalid = ["-bad.example", "bad-.example", "two..dots.org", "bad name.example", "a" * 64 + ".example"]
    for value in invalid:
        require(not module.FQDN(value).is_valid, "Invalid domain accepted: " + repr(value))
    require(not module.FQDN("localhost").is_valid, "Single label accepted by default policy")
    return {"checks": ["valid-domain", "absolute-relative", "empty-name", "bad-hyphens", "empty-label", "whitespace", "label-length", "single-label-policy"], "dns-network": "not_used"}

if __name__ == "__main__":
    raise SystemExit(main('fqdn', 'fqdn', functional))
