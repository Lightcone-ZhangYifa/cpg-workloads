#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise date parsing, calendar arithmetic, zones and invalid input."""
    value = module.get("2024-02-29T12:30:00+00:00")
    shifted = value.shift(days=1)
    require(shifted.format("YYYY-MM-DD HH:mm") == "2024-03-01 12:30", "Leap-day arithmetic failed")
    require(value.to("Asia/Shanghai").format("HH:mm ZZ") == "20:30 +08:00", "Time-zone conversion failed")
    require(module.get(value.isoformat()) == value, "ISO roundtrip failed")
    first, last = value.span("day")
    require(first.hour == 0 and last.hour == 23 and first <= value <= last, "Day bounds failed")
    next_month = value.shift(months=1)
    require((next_month.year, next_month.month, next_month.day) == (2024, 3, 29) and value.month == 2, "Month arithmetic or input preservation failed")
    raises(ValueError, lambda: module.get("not-a-date"), "Invalid date accepted")
    raises(ValueError, lambda: module.get(2024, 2, 30), "Invalid calendar date accepted")
    return {"checks": ["leap-day-arithmetic", "timezone-conversion", "iso-roundtrip", "day-span", "immutable-month-shift", "invalid-text", "invalid-calendar-date"]}

if __name__ == "__main__":
    raise SystemExit(main('arrow', 'arrow', functional))
