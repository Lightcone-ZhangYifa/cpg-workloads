#!/usr/bin/env python3
"""Installed functional check for pyyaml; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(yaml, work):
    """Round-trip plain configuration and reject invalid or executable YAML tags."""
    value = {"name": "compiler 中文", "seeds": [1, 3, 5], "enabled": True, "optional": None}
    text = yaml.safe_dump(value, allow_unicode=True, sort_keys=True)
    require(yaml.safe_load(text) == value, "Safe YAML round trip mismatch")
    docs = list(yaml.safe_load_all("a: 1\n---\nb: 2\n"))
    require(docs == [{"a": 1}, {"b": 2}], "Multiple YAML documents mismatch")
    raises(yaml.YAMLError, lambda: yaml.safe_load("a: [1, 2"), "Malformed YAML was accepted")
    raises(yaml.constructor.ConstructorError, lambda: yaml.safe_load("!!python/object/apply:builtins.str [1]"), "Python-object tag was accepted by safe_load")
    return {"checks": ["safe-unicode-roundtrip", "multiple-documents", "malformed-yaml", "python-tag-rejection"]}

if __name__ == "__main__":
    raise SystemExit(main('pyyaml', 'yaml', functional))
