#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise block, callable and iterable timing without timing thresholds."""
    import math
    with module.about_time() as block:
        answer = sum(range(100))
    require(answer == 4950 and block.duration >= 0 and math.isfinite(block.duration), "Context timing failed")
    timed = module.about_time(lambda value: value * value, 9)
    require(timed.result == 81 and timed.duration >= 0, "Callable timing/result failed")
    items = module.about_time([2, 3, 5])
    require(list(items) == [2, 3, 5] and items.count == 3, "Iterable timing/count failed")
    def broken():
        raise ValueError("intentional timing failure")
    raises(ValueError, lambda: module.about_time(broken), "Callable failure was suppressed")
    raises(UserWarning, lambda: module.about_time(3), "Invalid timing input accepted")
    require(bool(block.duration_human) and bool(timed.duration_human), "Human duration missing")
    return {"checks": ["context-duration", "callable-result", "iterable-count", "callable-failure-propagation", "invalid-input", "human-duration"]}

if __name__ == "__main__":
    raise SystemExit(main('about-time', 'about_time', functional))
