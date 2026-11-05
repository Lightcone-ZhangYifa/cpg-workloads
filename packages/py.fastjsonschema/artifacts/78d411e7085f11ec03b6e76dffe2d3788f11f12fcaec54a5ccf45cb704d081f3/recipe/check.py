#!/usr/bin/env python3
"""Installed fastjsonschema check using local schemas and deterministic invalid data."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(fjs, work):
    """Compile object/array/ref schemas, apply defaults and reject constraint errors."""
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
              "properties": {"count": {"type": "integer", "minimum": 1},
                             "label": {"type": "string", "minLength": 1, "default": "unnamed"}},
              "required": ["count"], "additionalProperties": False}
    validate = fjs.compile(schema)
    require(validate({"count": 3}) == {"count": 3, "label": "unnamed"}, "Default/object validation mismatch")
    for value in [{"count": 0}, {"count": "3"}, {"count": 2, "label": ""}, {"count": 1, "extra": 2}, {}]:
        raises(fjs.JsonSchemaValueException, lambda value=value: validate(value), "Invalid object accepted")
    sequence = fjs.compile({"type": "array", "items": {"type": "number"}, "minItems": 1, "uniqueItems": True})
    require(sequence([1, 2.5]) == [1, 2.5], "Array validation changed values")
    for value in [[], [1, 1], ["x"]]:
        raises(fjs.JsonSchemaValueException, lambda value=value: sequence(value), "Invalid array accepted")
    reference = fjs.compile({"definitions": {"positive": {"type": "integer", "minimum": 1}}, "$ref": "#/definitions/positive"})
    require(reference(7) == 7, "Local reference did not resolve")
    raises(fjs.JsonSchemaValueException, lambda: reference(-1), "Reference bypassed validation")
    raises(fjs.JsonSchemaDefinitionException, lambda: fjs.compile({"type": "not-a-json-type"}), "Invalid schema type accepted")
    return {"checks": ["compiled-object-schema", "defaults", "range-type-length-extra-required-errors",
                       "array-validation", "array-size-uniqueness-type-errors", "local-reference", "reference-error", "invalid-schema"],
            "scope": "draft-07 local schemas; no remote reference retrieval"}

if __name__ == "__main__":
    raise SystemExit(main("fastjsonschema", "fastjsonschema", functional))
