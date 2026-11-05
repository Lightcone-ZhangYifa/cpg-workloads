#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise decorated functions/classes, warning text and warnings-as-errors."""
    import warnings
    @module.deprecated(version="2.0", reason="use replacement")
    def old(value):
        """Original callable docstring."""
        return value * 2
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        require(old(4) == 8, "Decorated function changed result")
    require(len(captured) == 1 and issubclass(captured[0].category, DeprecationWarning), "Deprecation warning absent")
    require("use replacement" in str(captured[0].message) and "2.0" in str(captured[0].message), "Warning metadata missing")
    require(old.__name__ == "old" and old.__doc__ == "Original callable docstring.", "Callable metadata not preserved")
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        raises(DeprecationWarning, lambda: old(1), "Warning-as-error ignored")
    @module.deprecated(reason="old class")
    class Legacy:
        def __init__(self, value): self.value = value
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        require(Legacy(7).value == 7 and len(captured) == 1, "Decorated class failed")
    return {"checks": ["callable-result", "warning-category", "reason-version", "callable-metadata", "warnings-as-errors", "decorated-class"]}

if __name__ == "__main__":
    raise SystemExit(main('deprecated', 'deprecated', functional))
