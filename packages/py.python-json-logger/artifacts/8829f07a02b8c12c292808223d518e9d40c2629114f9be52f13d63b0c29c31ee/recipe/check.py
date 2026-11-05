#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Emit structured logs with Unicode, typed extras and exception data.'
    import io
    import json
    import logging
    formatter = installed_module("pythonjsonlogger.json")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(formatter.JsonFormatter("%(levelname)s %(message)s", json_ensure_ascii=False))
    logger = logging.Logger("cpg-json-probe", level=logging.INFO)
    logger.addHandler(handler)
    logger.info("编译", extra={"iteration": 7, "values": [1, 2]})
    try:
        raise ValueError("expected failure")
    except ValueError:
        logger.exception("caught")
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    require(records[0]["message"] == "编译" and records[0]["iteration"] == 7 and records[0]["values"] == [1, 2], "Structured record changed values")
    require(records[0]["levelname"] == "INFO", "Level field missing")
    require("ValueError: expected failure" in records[1]["exc_info"], "Exception detail missing")
    raises(ValueError, lambda: formatter.JsonFormatter("%(message)s", style="!"), "Invalid logging format style was accepted")
    handler.close()
    return {"checks": ["json-lines-output", "unicode-and-typed-extras", "level-field", "exception-record", "invalid-style"]}

if __name__ == '__main__':
    raise SystemExit(main('python-json-logger', 'pythonjsonlogger', functional))
