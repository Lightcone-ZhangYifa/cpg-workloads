#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Measure actual object graphs and show shared-reference deduplication.'
    asizeof = installed_module("pympler.asizeof")
    summary = installed_module("pympler.summary")
    shared = list(range(1000))
    one = asizeof.asizeof(shared)
    repeated = asizeof.asizeof([shared, shared])
    distinct = asizeof.asizeof([list(shared), list(shared)])
    require(one > 0 and repeated < distinct, "Shared-reference sizing did not deduplicate")
    detailed = asizeof.asized({"payload": shared}, detail=2)
    require(detailed.size >= detailed.flat > 0 and detailed.refs, "Detailed graph sizing failed")
    rows = summary.summarize([{}, {}, [], "abc"])
    require(any(row[0] == "dict" and row[1] == 2 and row[2] > 0 for row in rows), "Object type summary failed")
    return {"checks": ["recursive-object-size", "shared-reference-deduplication", "detailed-reference-report", "type-count-summary"], "shared_bytes": repeated, "distinct_bytes": distinct}

if __name__ == '__main__':
    raise SystemExit(main('pympler', 'pympler', functional))
