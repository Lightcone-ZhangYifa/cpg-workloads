#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Format and emit real log records through a configured stream handler."""
    import io
    import logging
    stream = io.StringIO()
    formatter = module.ColoredFormatter("%(log_color)s%(levelname)s:%(message)s", log_colors={"INFO": "green", "ERROR": "red"}, force_color=True)
    handler = logging.StreamHandler(stream); handler.setFormatter(formatter)
    logger = logging.getLogger("cpg.colorlog.functional"); logger.setLevel(logging.DEBUG); logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.info("count=%d", 3); logger.error("failure=%s", "expected")
    finally:
        logger.removeHandler(handler); handler.close()
    value = stream.getvalue()
    require("INFO:count=3" in value and "ERROR:failure=expected" in value and "\x1b[" in value, "Color/log interpolation failed")
    plain = module.ColoredFormatter("%(log_color)s%(message)s", no_color=True)
    record = logging.LogRecord("x", logging.INFO, "", 0, "plain", (), None)
    require(plain.format(record) == "plain", "Explicit no-color format failed")
    bad = module.ColoredFormatter("%(missing_attribute)s")
    raises(ValueError, lambda: bad.format(record), "Missing log field accepted")
    return {"checks": ["stream-handler-emission", "level-colors", "message-interpolation", "no-color-mode", "missing-field-error"]}

if __name__ == "__main__":
    raise SystemExit(main('colorlog', 'colorlog', functional))
