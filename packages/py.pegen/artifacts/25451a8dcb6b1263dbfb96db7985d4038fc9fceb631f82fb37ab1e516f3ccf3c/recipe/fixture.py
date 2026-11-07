"""Exercise a real pegen-generated parser; never evaluate input as Python."""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import tokenize
from pegen.tokenizer import Tokenizer

def load_parser(path):
    spec = importlib.util.spec_from_file_location("cpg_generated_expression", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GeneratedParser

def parse_text(parser_type, text):
    parser = parser_type(Tokenizer(tokenize.generate_tokens(io.StringIO(text).readline)))
    try:
        result = parser.start()
    except tokenize.TokenError as exc:
        message, (line, column) = exc.args
        lines = text.splitlines()
        source_line = lines[line - 1] if 0 < line <= len(lines) else ""
        raise SyntaxError(message, ("<expression>", line, column + 1, source_line)) from exc
    if result is None:
        raise parser.make_syntax_error("invalid expression")
    return result

def evaluate(node, variables=None):
    variables = variables or {}
    if node[0] == "num": return node[1]
    if node[0] == "var": return variables[node[1]]
    left, right = evaluate(node[1], variables), evaluate(node[2], variables)
    return {"add": lambda: left + right, "sub": lambda: left - right,
            "mul": lambda: left * right, "pow": lambda: left ** right}[node[0]]()

def verify(parser_file):
    parser = load_parser(parser_file)
    cases = []
    positives = [
        ("precedence", "2 + 3 * 4", ("add", ("num", 2), ("mul", ("num", 3), ("num", 4))), 14),
        ("parentheses", "(2 + 3) * 4", ("mul", ("add", ("num", 2), ("num", 3)), ("num", 4)), 20),
        ("left_associative", "9 - 3 - 1", ("sub", ("sub", ("num", 9), ("num", 3)), ("num", 1)), 5),
        ("right_associative", "2 ** 3 ** 2", ("pow", ("num", 2), ("pow", ("num", 3), ("num", 2))), 512),
        ("unicode_name", "变量 + 2", ("add", ("var", "变量"), ("num", 2)), 9),
        ("deep_nesting", "((1 + 2) * (3 + 4))", ("mul", ("add", ("num", 1), ("num", 2)), ("add", ("num", 3), ("num", 4))), 21),
    ]
    for name, text, expected, value in positives:
        actual = parse_text(parser, text)
        assert actual == expected, (name, actual, expected)
        assert evaluate(actual, {"变量": 7}) == value
        cases.append({"case": name, "input": text, "ast": actual, "value": value, "passed": True})
    negatives = [("missing_operand", "2 + * 3", 1, 5),
                 ("trailing_input", "2 3", 1, 3),
                 ("empty_input", "", 1, 1),
                 ("wrong_delimiter", "(2 + 3]", 1, 7),
                 ("float_rejected", "1.5", 1, 1),
                 ("exponent_rejected", "1e3", 1, 1),
                 ("imaginary_rejected", "1j", 1, 1),
                 ("hex_rejected", "0x10", 1, 1),
                 ("underscored_rejected", "1_000", 1, 1),
                 ("unclosed_parenthesis", "(2 + 3", 1, 1),
                 ("missing_final_operand", "2 +", 1, 4),
                 ("unsupported_operator", "2 / 1", 1, 3)]
    for name, text, line, column in negatives:
        try: parse_text(parser, text)
        except SyntaxError as exc:
            assert (exc.lineno, exc.offset) == (line, column), (name, exc.lineno, exc.offset)
            cases.append({"case": name, "input": text, "line": exc.lineno, "column": exc.offset, "passed": True})
        else: raise AssertionError("Invalid input was accepted: " + name)
    return {"resource_id": "py.pegen", "version": "0.3.0", "status": "passed", "test_count": len(cases),
            "scope": "standalone PyPI pegen Python-code generator, generated AST and rejection locations; not CPython C parser",
            "cases": cases}

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--parser", type=Path, required=True)
    p.add_argument("--report", type=Path)
    a=p.parse_args()
    result=verify(a.parser)
    if a.report: a.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))

