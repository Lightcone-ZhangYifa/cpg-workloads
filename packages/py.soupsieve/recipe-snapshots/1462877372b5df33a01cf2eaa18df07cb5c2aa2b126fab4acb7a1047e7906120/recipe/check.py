#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Compile structured CSS selectors and reject malformed selector syntax.'
    pattern = "article > p.item:nth-child(2n+1):not(.hidden), a[href^='https://']"
    selector = module.compile(pattern)
    require(selector.pattern == pattern and len(selector.selectors) == 2, "CSS selector compilation failed")
    require(module.compile(pattern) is selector, "Compiled selector cache did not reuse a live entry")
    require(module.escape("1st item") == "\\31 st\\ item", "CSS identifier escaping failed")
    raises(module.SelectorSyntaxError, lambda: module.compile("div["), "Malformed attribute selector accepted")
    raises(module.SelectorSyntaxError, lambda: module.compile(":not("), "Unclosed pseudo selector accepted")
    module.purge()
    require(module.compile(pattern).pattern == pattern, "Compile failed after cache purge")
    return {"checks": ["complex-css-compile", "selector-group-count", "compile-cache", "identifier-escape", "invalid-attribute", "invalid-pseudo", "cache-purge"], "scope": "CSS compilation/escaping only; DOM selection is qualified through BeautifulSoup separately."}

if __name__ == '__main__':
    raise SystemExit(main('soupsieve', 'soupsieve', functional))
