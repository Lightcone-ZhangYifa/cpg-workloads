#!/usr/bin/env python3
"""Installed functional check for Lark; all inputs are local and deterministic."""
from pathlib import Path
import io
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(lark, work):
    """Check parsing, precedence, transformations, parser serialization and errors."""
    grammar = r'''?start: sum
?sum: product | sum "+" product -> add | sum "-" product -> sub
?product: atom | product "*" atom -> mul
?atom: NUMBER -> number | "-" atom -> neg | "(" sum ")"
%import common.NUMBER
%import common.WS
%ignore WS
'''
    class Evaluate(lark.Transformer):
        def number(self, children): return int(children[0])
        def add(self, children): return children[0] + children[1]
        def sub(self, children): return children[0] - children[1]
        def mul(self, children): return children[0] * children[1]
        def neg(self, children): return -children[0]
    parser = lark.Lark(grammar, parser="lalr", propagate_positions=True)
    cases = {"2 + 3 * 4": 14, "(2 + 3) * 4": 20, "10 - 3 - 2": 5,
             "-2 * (3 + 1)": -8, "0": 0}
    for source, expected in cases.items():
        require(Evaluate().transform(parser.parse(source)) == expected, f"Wrong parse for {source}")
    tree = parser.parse("2 + 3 * 4")
    require(tree.meta.line == 1 and tree.meta.column == 1, "Source position was lost")
    stream = io.BytesIO(); parser.save(stream); stream.seek(0)
    restored = lark.Lark.load(stream)
    require(Evaluate().transform(restored.parse("(4 + 5) * 2")) == 18, "Parser serialization failed")
    raises(lark.exceptions.UnexpectedInput, lambda: parser.parse("2 + * 3"), "Malformed expression accepted")
    raises(lark.exceptions.GrammarError, lambda: lark.Lark("start: missing_rule"), "Undefined rule accepted")
    return {"checks": ["precedence-and-associativity", "transformer-known-answers", "source-positions",
                       "parser-serialization", "malformed-expression", "undefined-rule"], "expression_cases": len(cases)}

if __name__ == "__main__":
    raise SystemExit(main("lark", "lark", functional))
