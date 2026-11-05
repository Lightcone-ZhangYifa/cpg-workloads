#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Serialize nested Unicode data and roundtrip through the locked YAML dependency.'
    yaml = installed_module("yaml")
    data = {"label": "编译器", "values": [1, 2.5, None, True], "nested": {"key": "line1\nline2"}}
    result = module.dump(data)
    require(isinstance(result, str) and "编译器" in result, "Unicode YAML text was not produced")
    require(yaml.safe_load(result) == data, "YAML roundtrip changed values")
    target = work / "result.yaml"
    with target.open("w", encoding="utf-8") as stream:
        module.dump(data, dst=stream)
    require(yaml.safe_load(target.read_text()) == data, "Stream destination serialization failed")
    require(module.dump([]).strip() == "[]", "Empty sequence serialization failed")
    raises(AttributeError, lambda: module.dump(data, dst=object()), "Non-stream destination accepted")
    raises(TypeError, lambda: module.dump(data, dst=object(), stream=object()), "Conflicting destination arguments accepted")
    return {"checks": ["unicode-mapping", "nested-values-roundtrip", "stream-destination", "empty-sequence", "invalid-destination", "conflicting-destinations"]}

if __name__ == '__main__':
    raise SystemExit(main('pyaml', 'pyaml', functional))
