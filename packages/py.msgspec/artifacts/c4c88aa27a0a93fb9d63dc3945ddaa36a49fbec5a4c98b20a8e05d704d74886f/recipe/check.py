#!/usr/bin/env python3
"""Installed msgspec checks for typed JSON/MessagePack and constraint failures."""
from pathlib import Path
from typing import Annotated
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(ms, work):
    """Check typed codecs, schema generation, conversion and rejected field values."""
    class Row(ms.Struct, forbid_unknown_fields=True):
        identifier: Annotated[int, ms.Meta(ge=0)]
        values: list[float]
        label: str = "ok"
    value = Row(7, [1.5, 2.0])
    for codec, suffix in [(ms.json, "json"), (ms.msgpack, "msgpack")]:
        encoded = codec.encode(value)
        require(codec.decode(encoded, type=Row) == value, f"Typed {suffix} round trip failed")
        target = work / ("row." + suffix); target.write_bytes(encoded)
        require(codec.decode(target.read_bytes(), type=Row) == value, f"{suffix} file round trip failed")
    converted = ms.convert({"identifier": 2, "values": [3.0]}, type=Row)
    require(converted == Row(2, [3.0]) and ms.to_builtins(converted) == {"identifier": 2, "values": [3.0], "label": "ok"},
            "Typed conversion/defaults mismatch")
    schema = ms.json.schema(Row)
    definitions = schema.get("$defs", {})
    require("Row" in definitions and definitions["Row"]["properties"]["identifier"]["minimum"] == 0,
            "JSON schema lost the integer constraint")
    for raw in [b'{"identifier":-1,"values":[]}', b'{"identifier":"7","values":[]}',
                b'{"identifier":7,"values":[],"unknown":1}', b'{"values":[]}']:
        raises(ms.ValidationError, lambda raw=raw: ms.json.decode(raw, type=Row), "Invalid typed record accepted")
    raises(ms.DecodeError, lambda: ms.msgpack.decode(b"\x81"), "Truncated MessagePack accepted")
    raises(ms.ValidationError, lambda: ms.convert({"identifier": "2", "values": []}, type=Row), "Strict conversion accepted a string integer")
    return {"checks": ["typed-json-roundtrip", "typed-messagepack-roundtrip", "file-roundtrips", "conversion-and-defaults",
                       "builtin-conversion", "constraint-schema", "negative-type-extra-and-missing-field-errors",
                       "truncated-messagepack", "strict-conversion"]}

if __name__ == "__main__":
    raise SystemExit(main("msgspec", "msgspec", functional))
