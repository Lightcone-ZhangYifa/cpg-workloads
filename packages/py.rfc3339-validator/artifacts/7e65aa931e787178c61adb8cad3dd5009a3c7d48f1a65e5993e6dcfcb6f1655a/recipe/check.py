#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Accept real RFC 3339 dates and reject impossible calendar and zone values.'
    valid = ["2024-02-29T23:59:59Z", "2026-10-26T12:34:56.123+08:00", "2000-01-01T00:00:00-05:30"]
    invalid = ["2023-02-29T12:00:00Z", "2024-13-01T00:00:00Z", "2024-01-01T25:00:00Z", "2024-01-01", "2024-01-01T00:00:00+25:00"]
    require(all(module.validate_rfc3339(value) for value in valid), "Valid timestamp rejected")
    require(not any(module.validate_rfc3339(value) for value in invalid), "Invalid timestamp accepted")
    return {"checks": ["leap-date", "fractional-seconds", "signed-offset", "invalid-calendar", "invalid-hour", "missing-time", "invalid-zone"], "accepted": len(valid), "rejected": len(invalid)}

if __name__ == '__main__':
    raise SystemExit(main('rfc3339-validator', 'rfc3339_validator', functional))
