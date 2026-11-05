#!/usr/bin/env python3
"""Installed orjson checks for typed values, byte output and rejected inputs."""
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(orjson, work):
    """Check JSON round trips, dataclasses, date formatting and malformed inputs."""
    data = {"text": "编译器", "values": [1, 2.5, True, None], "nested": {"x": -3}}
    encoded = orjson.dumps(data, option=orjson.OPT_SORT_KEYS)
    require(isinstance(encoded, bytes) and orjson.loads(encoded) == data, "UTF-8 byte JSON round trip failed")
    require(orjson.dumps({"z": 1, "a": 2}, option=orjson.OPT_SORT_KEYS) == b'{"a":2,"z":1}', "Sorted keys mismatch")
    @dataclass
    class Row:
        name: str
        count: int
    require(orjson.loads(orjson.dumps(Row("compile", 4))) == {"name": "compile", "count": 4}, "Dataclass encoding failed")
    timestamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    require(orjson.loads(orjson.dumps(timestamp, option=orjson.OPT_UTC_Z)) == "2026-01-02T03:04:05Z", "UTC timestamp mismatch")
    require(orjson.loads(orjson.dumps({1: "one"}, option=orjson.OPT_NON_STR_KEYS)) == {"1": "one"}, "Non-string-key option failed")
    require(orjson.dumps(float("nan")) == b"null", "Nonfinite float contract mismatch")
    target = work / "data.json"; target.write_bytes(encoded)
    require(orjson.loads(target.read_bytes()) == data, "JSON file round trip failed")
    for raw in [b'{"a":', b'"\xff"', b'{"a":1,}']:
        raises(orjson.JSONDecodeError, lambda raw=raw: orjson.loads(raw), "Malformed JSON accepted")
    raises(TypeError, lambda: orjson.dumps(1 << 100), "Out-of-range integer accepted")
    cycle = []; cycle.append(cycle)
    raises(TypeError, lambda: orjson.dumps(cycle), "Cyclic input accepted")
    return {"checks": ["utf8-json-roundtrip", "sorted-keys", "dataclass", "utc-datetime", "non-string-keys",
                       "nonfinite-float-contract", "file-roundtrip", "invalid-json-and-utf8", "integer-range", "cyclic-input"]}

if __name__ == "__main__":
    raise SystemExit(main("orjson", "orjson", functional))
