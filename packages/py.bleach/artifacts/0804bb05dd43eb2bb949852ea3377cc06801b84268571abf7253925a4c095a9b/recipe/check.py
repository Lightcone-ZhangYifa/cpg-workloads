#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise HTML allowlists, protocol rejection and CSS sanitization."""
    dirty = '<a href="javascript:alert(1)" onclick="bad()">link</a><b>bold</b><script>bad()</script>'
    clean = module.clean(dirty, tags=["a", "b"], attributes={"a": ["href"]}, protocols=["https"], strip=True)
    require("javascript:" not in clean and "onclick" not in clean and "<script" not in clean, "Rejected HTML survived sanitization")
    require("<b>bold</b>" in clean and "link" in clean, "Permitted HTML was lost")
    require(module.clean("<em>x</em>", tags=[]) == "&lt;em&gt;x&lt;/em&gt;", "Escaping fallback failed")
    css = installed_module("bleach.css_sanitizer")
    sanitizer = css.CSSSanitizer(allowed_css_properties=["color"])
    styled = module.clean('<p style="color:red;position:absolute">x</p>', tags=["p"], attributes=["style"], css_sanitizer=sanitizer)
    require("color:red" in styled and "position" not in styled, "CSS allowlist failed")
    linked = module.linkify("Visit https://example.org/")
    require('href="https://example.org/"' in linked and 'rel="nofollow"' in linked, "Linkification failed")
    raises(TypeError, lambda: module.clean(None), "Non-text input accepted")
    return {"checks": ["tag-attribute-protocol-allowlist", "retained-markup", "escaping", "css-allowlist", "linkify", "invalid-input"], "scope": "Selected local sanitization cases; not a complete security audit"}

if __name__ == "__main__":
    raise SystemExit(main('bleach', 'bleach', functional))
