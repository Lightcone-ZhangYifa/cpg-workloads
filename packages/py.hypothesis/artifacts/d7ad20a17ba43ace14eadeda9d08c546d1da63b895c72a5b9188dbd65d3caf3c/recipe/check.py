#!/usr/bin/env python3
"""Installed functional check for hypothesis; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(hypothesis, work):
    """Execute generated examples and find a known boundary counterexample."""
    from hypothesis import given, settings, find, strategies as st
    from hypothesis.errors import NoSuchExample
    seen = []
    configured = settings(max_examples=30, derandomize=True, database=None, deadline=None)
    @configured
    @given(st.lists(st.integers(min_value=-100, max_value=100), max_size=12))
    def property_check(values):
        seen.append(tuple(values))
        require(sum(values) == sum(reversed(values)), "Integer reversal property failed")
    property_check()
    require(len(seen) >= 20, "Insufficient generated examples were executed")
    boundary = find(st.integers(min_value=0, max_value=100), lambda n: n > 16, settings=configured)
    require(boundary == 17, "Counterexample shrinking mismatch")
    raises(NoSuchExample, lambda: find(st.just(1), lambda n: n == 2, settings=configured), "Impossible predicate unexpectedly found an example")
    return {"checks": ["generated-property-execution", "counterexample-and-shrinking", "no-such-example"], "examples_executed": len(seen), "smallest_boundary_example": boundary}

if __name__ == "__main__":
    raise SystemExit(main('hypothesis', 'hypothesis', functional))
