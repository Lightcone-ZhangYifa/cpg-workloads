#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Render stable table layouts, numeric precision and missing values.'
    rows = [["alpha", 1.2345], ["beta", 2.0]]
    rendered = module.tabulate(rows, headers=["name", "value"], tablefmt="github", floatfmt=".2f")
    require("name" in rendered and "value" in rendered and "1.23" in rendered and "2.00" in rendered, "Header/float table rendering failed")
    require(len(rendered.splitlines()) == 4 and all(line.startswith("|") for line in rendered.splitlines()), "GitHub table structure failed")
    html = module.tabulate([["<tag>", None]], headers=["text", "missing"], tablefmt="html", missingval="NA")
    require("&lt;tag&gt;" in html and "<tag>" not in html and "NA" in html, "HTML escaping or missing value rendering failed")
    empty = module.tabulate([], headers=["A"], tablefmt="plain")
    require(empty.strip() == "A", "Empty table header contract failed")
    return {"checks": ["github-table-shape", "float-precision", "html-escaping", "missing-value", "empty-table"]}

if __name__ == '__main__':
    raise SystemExit(main('tabulate', 'tabulate', functional))
