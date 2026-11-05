#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(parso, work):
    """Check concrete syntax preservation, name indexing and error recovery."""
    source = '# comment\ndef square(x):\n    return x * x\nvalue = square(7)\n'
    module = parso.parse(source, version='3.12', error_recovery=False)
    require(module.get_code() == source, 'Concrete source round trip failed')
    functions = list(module.iter_funcdefs())
    require(len(functions) == 1 and functions[0].name.value == 'square', 'Function traversal failed')
    names = module.get_used_names()
    require(len(names['square']) == 2 and len(names['x']) == 3, 'Name index mismatch')
    require(functions[0].start_pos == (2, 0), 'Function position mismatch')
    grammar = parso.load_grammar(version='3.12')
    require(grammar.parse(source).get_code() == source, 'Explicit grammar parse failed')
    bad = 'def broken(:\n    pass\n'
    raises(parso.ParserSyntaxError, lambda: parso.parse(bad, error_recovery=False), 'Strict parse accepted invalid syntax')
    recovered = parso.parse(bad, error_recovery=True)
    def walk(node):
        yield node
        for item in getattr(node, 'children', []): yield from walk(item)
    require(any(node.type in ('error_node', 'error_leaf') for node in walk(recovered)), 'Recovery did not retain error nodes')
    require(recovered.get_code() == bad, 'Error recovery lost original source')
    return {'checks': ['lossless-source', 'function-traversal', 'used-name-index', 'positions', 'explicit-grammar', 'strict-error', 'error-recovery-nodes', 'invalid-source-preservation']}

if __name__ == "__main__":
    raise SystemExit(main('parso', 'parso', functional))
