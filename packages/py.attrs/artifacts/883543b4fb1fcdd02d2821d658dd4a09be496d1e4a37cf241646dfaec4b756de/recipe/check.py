#!/usr/bin/env python3
"""Installed attrs check for conversion, validation, immutable data and factories."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require

def functional(attrs, work):
    """Check model construction, independent defaults, evolution and field failures."""
    @attrs.define
    class Task:
        count: int = attrs.field(converter=int, validator=attrs.validators.ge(1))
        name: str = attrs.field(validator=attrs.validators.instance_of(str), default="task")
        labels: list = attrs.field(factory=list)
    first = Task("3"); second = Task(4)
    require(first.count == 3 and attrs.has(Task), "Converter/model metadata failed")
    first.labels.append("cpu")
    require(second.labels == [] and first.labels is not second.labels, "Factory default was shared")
    require(attrs.asdict(first) == {"count": 3, "name": "task", "labels": ["cpu"]}, "asdict mismatch")
    updated = attrs.evolve(first, count="7", name="new")
    require(updated.count == 7 and first.count == 3 and updated.name == "new", "Evolution failed")
    @attrs.frozen
    class Fixed:
        value: int
    fixed = Fixed(5)
    exceptions = installed_module("attr.exceptions")
    raises(exceptions.FrozenInstanceError, lambda: setattr(fixed, "value", 6), "Frozen instance mutation accepted")
    raises(ValueError, lambda: Task(0), "Range validator accepted zero")
    raises(TypeError, lambda: Task(1, name=7), "Type validator accepted a number")
    raises(ValueError, lambda: attrs.evolve(first, count=0), "Evolution bypassed validation")
    return {"checks": ["field-converter", "model-metadata", "independent-factory-defaults", "asdict",
                       "evolve", "frozen-mutation", "range-validator", "type-validator", "evolve-validation"]}

if __name__ == "__main__":
    raise SystemExit(main("attrs", "attrs", functional))
