#!/usr/bin/env python3
"""Installed pyparsing check for expression grammar, named fields and errors."""
from pathlib import Path
import operator
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(pp, work):
    """Check precedence/associativity, parse actions, names and complete consumption."""
    number = pp.Word(pp.nums).set_parse_action(lambda tokens: int(tokens[0]))
    operations = {"+": operator.add, "-": operator.sub, "*": operator.mul}
    def binary(tokens):
        parts = tokens[0]; value = parts[0]
        for index in range(1, len(parts), 2): value = operations[parts[index]](value, parts[index + 1])
        return value
    expression = pp.infix_notation(number, [(pp.Literal("-"), 1, pp.OpAssoc.RIGHT, lambda tokens: -tokens[0][1]),
                              (pp.Literal("*"), 2, pp.OpAssoc.LEFT, binary),
                              (pp.one_of("+ -"), 2, pp.OpAssoc.LEFT, binary)])
    cases = {"2+3*4": 14, "(2+3)*4": 20, "10-3-2": 5, "-2*(3+1)": -8}
    for source, expected in cases.items(): require(expression.parse_string(source, parse_all=True).as_list() == [expected], "Expression value mismatch")
    assignment = pp.Word(pp.alphas, pp.alphanums + "_")("name") + pp.Suppress("=") + expression("value")
    result = assignment.parse_string("kernel_count = 2 + 3 * 4", parse_all=True)
    require(result["name"] == "kernel_count" and result["value"] == 14, "Named results mismatch")
    csv = pp.DelimitedList(pp.QuotedString('"') | pp.Word(pp.alphanums))
    require(csv.parse_string('one,"two,three",four', parse_all=True).as_list() == ["one", "two,three", "four"], "Quoted delimiter parsing failed")
    for source in ["2 + * 3", "2 + 3 trailing", "(2 + 3"]:
        raises(pp.ParseException, lambda source=source: expression.parse_string(source, parse_all=True), "Invalid or trailing input accepted")
    return {"checks": ["precedence-and-associativity", "parse-actions", "named-results", "quoted-delimiters",
                       "malformed-expression", "complete-input-consumption", "unbalanced-parenthesis"], "expression_cases": len(cases)}

if __name__ == "__main__":
    raise SystemExit(main("pyparsing", "pyparsing", functional))
