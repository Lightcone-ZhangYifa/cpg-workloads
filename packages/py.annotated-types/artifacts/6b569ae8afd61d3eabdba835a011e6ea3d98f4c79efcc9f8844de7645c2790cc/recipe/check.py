#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise constraint metadata and predicates; metadata alone is not validation."""
    import dataclasses
    from typing import Annotated, get_args
    interval = module.Interval(gt=0, le=10)
    require(list(interval) == [module.Gt(0), module.Le(10)], "Interval expansion failed")
    require(list(module.Len(2, 5)) == [module.MinLen(2), module.MaxLen(5)], "Length metadata expansion failed")
    metadata = get_args(Annotated[int, module.Gt(0), module.MultipleOf(2)])
    require(metadata[1:] == (module.Gt(0), module.MultipleOf(2)), "Annotated roundtrip failed")
    predicate = module.Predicate(lambda value: value % 2 == 0)
    require(predicate.func(4) is True and predicate.func(3) is False, "Predicate positive/negative failed")
    bound = module.Gt(3)
    require(bound == module.Gt(3) and hash(bound) == hash(module.Gt(3)), "Metadata equality/hash failed")
    raises(dataclasses.FrozenInstanceError, lambda: setattr(bound, "gt", 4), "Frozen bound accepted mutation")
    raises(TypeError, lambda: module.Interval(unrecognized=1), "Unknown metadata field accepted")
    return {"checks": ["interval-expansion", "length-expansion", "annotated-roundtrip", "predicate-positive-negative", "equality-hash", "frozen-metadata", "invalid-field"], "scope": "Constraint metadata API, not a standalone validator"}

if __name__ == "__main__":
    raise SystemExit(main('annotated-types', 'annotated_types', functional))
