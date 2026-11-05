#!/usr/bin/env python3
"""Installed functional check for jsonschema; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(js, work):
    """Validate a local-only schema and exercise nested, format and schema errors."""
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": {"seed": {"type": "integer", "minimum": 0}}, "type": "object", "required": ["seed"], "properties": {"seed": {"$ref": "#/$defs/seed"}}, "additionalProperties": False}
    validator = js.Draft202012Validator(schema)
    validator.check_schema(schema)
    validator.validate({"seed": 7})
    raises(js.ValidationError, lambda: validator.validate({"seed": -1}), "Minimum was ignored")
    raises(js.ValidationError, lambda: validator.validate({"seed": 1, "extra": True}), "Unexpected property was accepted")
    raises(js.SchemaError, lambda: js.Draft202012Validator.check_schema({"type": 123}), "Invalid schema was accepted")
    js.validate("2026-10-25", {"type": "string", "format": "date"}, format_checker=js.FormatChecker())
    raises(js.ValidationError, lambda: js.validate("not-a-date", {"format": "date"}, format_checker=js.FormatChecker()), "Explicit date format check did not reject invalid data")
    return {"checks": ["draft2020-local-reference", "minimum", "extra-property", "invalid-schema", "explicit-format"], "network_references": "not_used"}

if __name__ == "__main__":
    raise SystemExit(main('jsonschema', 'jsonschema', functional))
