#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(at, work):
    """Check AST token boundaries, source slicing and Unicode offsets."""
    import ast
    source = 'def calc(x):\n    return x + 42  # answer\n'
    parsed = at.ASTTokens(source, parse=True)
    expression = next(node for node in ast.walk(parsed.tree) if isinstance(node, ast.BinOp))
    require(parsed.get_text(expression) == 'x + 42', 'Expression text mismatch')
    start, end = parsed.get_text_range(expression)
    require(source[start:end] == 'x + 42', 'Token source range mismatch')
    require(expression.first_token.string == 'x' and expression.last_token.string == '42', 'AST token markers wrong')
    original_tree = ast.parse(source)
    marked = at.ASTTokens(source, tree=original_tree)
    require(marked.get_text(original_tree.body[0]) == source[:source.index('  # answer')], 'Externally parsed AST marking failed')
    unicode_source = '变量 = 7\nresult = 变量 + 2\n'
    unicode_tree = at.ASTTokens(unicode_source, parse=True)
    names = [node for node in ast.walk(unicode_tree.tree) if isinstance(node, ast.Name) and node.id == '变量']
    require(len(names) == 2 and all(unicode_tree.get_text(node) == '变量' for node in names), 'UTF-8 AST offsets failed')
    line_numbers = at.LineNumbers(unicode_source)
    require(line_numbers.offset_to_line(unicode_source.index('result')) == (2, 0), 'Offset to line conversion failed')
    raises(SyntaxError, lambda: at.ASTTokens('def broken(:', parse=True), 'Invalid Python accepted')
    return {'checks': ['ast-token-markers', 'exact-source-slices', 'source-ranges', 'existing-ast-marking', 'unicode-identifiers', 'line-offsets', 'syntax-error']}

if __name__ == "__main__":
    raise SystemExit(main('asttokens', 'asttokens', functional))
