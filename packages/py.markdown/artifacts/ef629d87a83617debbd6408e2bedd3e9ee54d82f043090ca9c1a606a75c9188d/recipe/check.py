#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Render Markdown with fenced code and tables using installed extensions.'
    source = "# Compiler\n\n**fast** & safe\n\n```python\nx = 1\n```\n\n| a | b |\n| - | - |\n| 1 | 2 |\n"
    result = module.markdown(source, extensions=["fenced_code", "tables"])
    require("<h1>Compiler</h1>" in result and "<strong>fast</strong> &amp; safe" in result, "Heading/text rendering failed")
    require('<code class="language-python">x = 1' in result, "Fenced code was not rendered")
    require("<table>" in result and "<td>2</td>" in result, "Table extension failed")
    raises(ModuleNotFoundError, lambda: module.markdown("x", extensions=["cpg_missing_markdown_extension_421"]), "Missing extension was silently accepted")
    return {"checks": ["heading-render", "inline-format-and-escaping", "fenced-code", "table-extension", "missing-extension"]}

if __name__ == '__main__':
    raise SystemExit(main('markdown', 'markdown', functional))
