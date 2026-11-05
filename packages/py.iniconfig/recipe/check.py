#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Parse sections, typed values, line locations and malformed INI input."""
    fixture = work / "settings.ini"
    fixture.write_text('[build]\ncount = 3\nname = compiler\n\n[paths]\nroot = /tmp/project\n')
    config = module.IniConfig(str(fixture))
    require(config["build"]["name"] == "compiler" and config.get("build", "count", convert=int) == 3, "INI value/typed conversion failed")
    require(config.lineof("build", "count") == 2, "INI one-based line mapping failed")
    require(config.get("build", "missing", default="fallback") == "fallback", "Default value failed")
    require(config.sections["paths"]["root"] == "/tmp/project", "Second section failed")
    raises(KeyError, lambda: config["missing"], "Missing section accepted")
    raises(module.ParseError, lambda: module.IniConfig("broken.ini", data="orphan = 1\n"), "Orphan key accepted")
    raises(module.ParseError, lambda: module.IniConfig("duplicate.ini", data="[x]\na=1\na=2\n"), "Duplicate key accepted")
    return {"checks": ["section-values", "typed-conversion", "line-location", "default-value", "multiple-sections", "missing-section", "orphan-key", "duplicate-key"]}

if __name__ == "__main__":
    raise SystemExit(main('iniconfig', 'iniconfig', functional))
