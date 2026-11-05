#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(markdown_it, work):
    """Check token structure, inline markup, code fences and safe URL/HTML handling."""
    parser = markdown_it.MarkdownIt('commonmark',{'html':False})
    source = '# Heading\n\n*one* **two**\n\n```c\nint x;\n```\n'
    tokens = parser.parse(source)
    require([t.type for t in tokens] == ['heading_open','inline','heading_close','paragraph_open','inline','paragraph_close','fence'], 'Block token structure mismatch')
    require(tokens[0].tag == 'h1' and tokens[-1].info == 'c' and tokens[-1].content == 'int x;\n', 'Heading/fence metadata wrong')
    inline = [t.type for t in tokens[4].children]
    require('em_open' in inline and 'strong_open' in inline, 'Inline emphasis tokens missing')
    rendered = parser.render(source)
    require('<h1>Heading</h1>' in rendered and '<em>one</em>' in rendered and 'class="language-c"' in rendered, 'HTML rendering lost structure')
    require('&lt;script&gt;' in parser.render('<script>alert(1)</script>'), 'Disabled HTML was not escaped')
    require('href="javascript:' not in parser.render('[bad](javascript:alert(1))'), 'Unsafe link scheme rendered as hyperlink')
    require('href="https://example.invalid/"' in parser.render('[ok](https://example.invalid/)'), 'Safe link was not rendered')
    raises(KeyError, lambda: markdown_it.MarkdownIt('cpg-missing-preset'), 'Unknown preset accepted')
    return {'checks':['block-token-inventory','heading-and-code-fence','inline-tokens','html-rendering','raw-html-escaping','unsafe-url-rejection','safe-link','unknown-preset'], 'scope':'CommonMark parser/rendering; no network retrieval'}

if __name__ == "__main__":
    raise SystemExit(main('markdown-it-py', 'markdown_it', functional))
