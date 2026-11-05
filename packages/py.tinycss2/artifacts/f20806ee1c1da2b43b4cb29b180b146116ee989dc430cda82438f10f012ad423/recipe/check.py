#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Parse CSS rules and bytes and inspect syntax error nodes.'
    css = "p { color: red; margin: 1px 2px; }"
    rules = module.parse_stylesheet(css, skip_whitespace=True, skip_comments=True)
    require(len(rules) == 1 and rules[0].type == "qualified-rule", "Qualified rule parse failed")
    declarations = module.parse_declaration_list(rules[0].content, skip_whitespace=True)
    require([item.lower_name for item in declarations] == ["color", "margin"], "Declaration names differ")
    require(module.serialize(rules) == css, "CSS serialization failed")
    errors = module.parse_declaration_list("color red;", skip_whitespace=True)
    require(any(item.type == "error" for item in errors), "Invalid declaration produced no error node")
    decoded, encoding = module.parse_stylesheet_bytes(b'p { content: "caf\xc3\xa9"; }', protocol_encoding="utf-8")
    require(encoding.name == "utf-8" and "café" in module.serialize(decoded), "Byte CSS decoding failed")
    return {"checks": ["qualified-rule", "declaration-list", "serialization", "invalid-declaration-node", "byte-input-encoding"]}

if __name__ == '__main__':
    raise SystemExit(main('tinycss2', 'tinycss2', functional))
