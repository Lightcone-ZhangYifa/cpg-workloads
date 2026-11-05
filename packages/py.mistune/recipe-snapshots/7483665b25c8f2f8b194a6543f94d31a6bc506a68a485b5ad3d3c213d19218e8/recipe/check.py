#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Render escaped HTML and structured Markdown with a selected plugin.'
    renderer = module.create_markdown(escape=True, plugins=["table"])
    html = renderer("# Title\n\n<script>alert(1)</script>\n\n**bold**\n\n| A | B |\n| - | - |\n| 1 | 2 |\n")
    require("<h1>Title</h1>" in html and "<strong>bold</strong>" in html, "Markdown rendering failed")
    require("<script>" not in html and "&lt;script&gt;" in html, "Raw HTML escaping failed")
    require("<table>" in html and "<td>2</td>" in html, "Table plugin failed")
    ast = module.create_markdown(renderer="ast")("one **two**")
    require(ast[0]["type"] == "paragraph" and any(node["type"] == "strong" for node in ast[0]["children"]), "AST output failed")
    return {"checks": ["html-render", "raw-html-escaping", "table-plugin", "structured-ast"]}

if __name__ == '__main__':
    raise SystemExit(main('mistune', 'mistune', functional))
