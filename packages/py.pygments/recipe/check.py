#!/usr/bin/env python3
"""Installed Pygments check for semantic tokens and HTML/terminal formatting."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require

def functional(pygments, work):
    """Check Python tokens, lossless text reconstruction, escaping and lookup errors."""
    lexers = installed_module("pygments.lexers"); formatters = installed_module("pygments.formatters")
    tokens = installed_module("pygments.token"); util = installed_module("pygments.util")
    source = "# kernel\ndef answer(x):\n    return x + 42\n"
    lexer = lexers.get_lexer_by_name("python")
    rows = list(pygments.lex(source, lexer))
    require("".join(value for _, value in rows) == source, "Tokenization lost source text")
    require(any(kind in tokens.Keyword and value == "def" for kind, value in rows), "Function keyword token missing")
    require(any(kind in tokens.Name.Function and value == "answer" for kind, value in rows), "Function-name token missing")
    require(any(kind in tokens.Number.Integer and value == "42" for kind, value in rows), "Integer token missing")
    require(any(kind in tokens.Comment and "kernel" in value for kind, value in rows), "Comment token missing")
    formatted_source = 'if x < 3:\n    print("a&b")\n'
    html = pygments.highlight(formatted_source, lexer, formatters.HtmlFormatter(nowrap=True))
    require("&lt;" in html and "&amp;" in html and "<span" in html, "HTML formatting/escaping failed")
    terminal = pygments.highlight(source, lexer, formatters.TerminalFormatter())
    require("\x1b[" in terminal and "answer" in terminal, "Terminal formatting failed")
    guessed = lexers.guess_lexer_for_filename("kernel.py", source)
    require("python" in guessed.aliases, "Filename lexer lookup selected another language")
    raises(util.ClassNotFound, lambda: lexers.get_lexer_by_name("cpg-nonexistent-lexer"), "Unknown lexer accepted")
    raises(util.ClassNotFound, lambda: formatters.get_formatter_by_name("cpg-nonexistent-formatter"), "Unknown formatter accepted")
    return {"checks": ["lossless-tokenization", "keyword-function-number-comment-tokens", "html-escaping",
                       "terminal-ansi", "filename-lookup", "unknown-lexer", "unknown-formatter"], "token_count": len(rows)}

if __name__ == "__main__":
    raise SystemExit(main("pygments", "pygments", functional))
