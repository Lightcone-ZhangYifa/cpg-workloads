#!/usr/bin/env python3
"""Installed functional check for pydantic; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pd, work):
    """Check strict typed models, range errors, extra fields and JSON round trips."""
    class Configuration(pd.BaseModel):
        model_config = pd.ConfigDict(strict=True, extra="forbid")
        seed: int = pd.Field(ge=0)
        label: str
    model = Configuration(seed=17, label="中文")
    require(Configuration.model_validate_json(model.model_dump_json()) == model, "Model JSON round trip mismatch")
    require(model.model_dump() == {"seed": 17, "label": "中文"}, "Model field mismatch")
    raises(pd.ValidationError, lambda: Configuration(seed="17", label="x"), "Strict integer validation was bypassed")
    raises(pd.ValidationError, lambda: Configuration(seed=-1, label="x"), "Range validation was bypassed")
    raises(pd.ValidationError, lambda: Configuration(seed=1, label="x", extra=1), "Extra field was accepted")
    schema = Configuration.model_json_schema()
    require(schema["properties"]["seed"]["minimum"] == 0, "Generated schema lost the bound")
    return {"checks": ["strict-model", "json-roundtrip", "wrong-type", "range", "extra-field", "generated-schema"]}

if __name__ == "__main__":
    raise SystemExit(main('pydantic', 'pydantic', functional))
