#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Exercise runtime typing helpers, TypedDict keys and structural protocols.'
    class Record(module.TypedDict):
        name: module.Required[str]
        value: module.NotRequired[int]
    require(Record.__required_keys__ == frozenset({"name"}) and Record.__optional_keys__ == frozenset({"value"}), "TypedDict key metadata failed")
    marked = module.Annotated[int, "positive"]
    require(module.get_args(marked) == (int, "positive"), "Annotated metadata failed")
    require(module.get_args(module.Literal["a", "b"]) == ("a", "b"), "Literal metadata failed")
    @module.runtime_checkable
    class HasRun(module.Protocol):
        def run(self): ...
    class Runner:
        def run(self): return 7
    require(isinstance(Runner(), HasRun) and not isinstance(object(), HasRun), "Runtime structural protocol failed")
    class StaticOnly(module.Protocol):
        def run(self): ...
    raises(TypeError, lambda: isinstance(Runner(), StaticOnly), "Unchecked runtime protocol accepted")
    return {"checks": ["typeddict-required-optional", "annotated-metadata", "literal-metadata", "runtime-protocol", "protocol-negative", "non-runtime-protocol-error"]}

if __name__ == '__main__':
    raise SystemExit(main('typing-extensions', 'typing_extensions', functional))
