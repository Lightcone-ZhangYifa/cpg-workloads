#!/usr/bin/env python3
"""Executable acceptance: custom xDSL dialect, verification, rewrite and interpreter."""
from __future__ import annotations

import argparse
import importlib.metadata
import io
import json
import subprocess
from pathlib import Path

from xdsl.context import Context
from xdsl.dialects import arith, builtin, func
from xdsl.dialects.builtin import i32
from xdsl.interpreter import Interpreter, InterpreterFunctions, impl, register_impls
from xdsl.interpreters.arith import ArithFunctions
from xdsl.interpreters.func import FuncFunctions
from xdsl.ir import Dialect
from xdsl.irdl import IRDLOperation, irdl_op_definition, operand_def, result_def, traits_def
from xdsl.parser import Parser
from xdsl.pattern_rewriter import PatternRewriter, PatternRewriteWalker, RewritePattern, op_type_rewrite_pattern
from xdsl.printer import Printer
from xdsl.traits import Pure
from xdsl.utils.exceptions import ParseError, VerifyException


@irdl_op_definition
class DoubleOp(IRDLOperation):
    """Pure wrapping i32 double; deliberately has a narrow, explicit type contract."""

    name = "cpg.double"
    input = operand_def(i32)
    output = result_def(i32)
    traits = traits_def(Pure())


CPG = Dialect("cpg", [DoubleOp], [])


def signed32(value: int) -> int:
    return ((value + 2**31) % 2**32) - 2**31


@register_impls
class CPGFunctions(InterpreterFunctions):
    @impl(DoubleOp)
    def run_double(self, interpreter, op, args):
        return (signed32(args[0] * 2),)


class LowerDouble(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DoubleOp, rewriter: PatternRewriter):
        rewriter.replace(op, arith.AddiOp(op.input, op.input))


PROGRAM = """builtin.module {
  func.func @main(%arg0: i32) -> i32 {
    %value = "cpg.double"(%arg0) : (i32) -> i32
    func.return %value : i32
  }
}
"""


def context():
    ctx = Context()
    for dialect in (builtin.Builtin, func.Func, arith.Arith, CPG):
        ctx.load_dialect(dialect)
    return ctx


def printed(module):
    stream = io.StringIO()
    Printer(stream=stream).print_op(module)
    return stream.getvalue() + "\n"


def execute(module, value):
    interpreter = Interpreter(module)
    interpreter.register_implementations(FuncFunctions())
    interpreter.register_implementations(ArithFunctions())
    interpreter.register_implementations(CPGFunctions())
    return interpreter.call_op("main", (value,))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--entrypoint", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    assert importlib.metadata.version("xdsl") == "0.74.0"
    module = Parser(context(), PROGRAM).parse_module()
    module.verify()
    before_text = printed(module)
    reparsed = Parser(context(), before_text).parse_module()
    reparsed.verify()
    assert module.is_structurally_equivalent(reparsed)
    assert printed(reparsed) == before_text
    values = [-2147483648, -1234567, -1, 0, 1, 21, 1234567, 2147483647]
    before = {str(value): execute(module, value)[0] for value in values}
    assert sum(isinstance(op, DoubleOp) for op in module.walk()) == 1
    assert PatternRewriteWalker(LowerDouble()).rewrite_module(module)
    module.verify()
    assert not any(isinstance(op, DoubleOp) for op in module.walk())
    assert sum(isinstance(op, arith.AddiOp) for op in module.walk()) == 1
    after = {str(value): execute(module, value)[0] for value in values}
    expected = {str(value): signed32(value * 2) for value in values}
    assert before == after == expected
    after_text = printed(module)
    final = Parser(context(), after_text).parse_module()
    final.verify()
    assert module.is_structurally_equivalent(final)
    assert not PatternRewriteWalker(LowerDouble()).rewrite_module(module)
    errors = {}
    for name, source in {
        "wrong_operand_and_result_type": PROGRAM.replace("i32", "f32"),
        "unknown_operation": PROGRAM.replace("cpg.double", "cpg.missing"),
        "missing_operand": PROGRAM.replace('"cpg.double"(%arg0) : (i32)', '"cpg.double"() : ()'),
    }.items():
        try:
            bad = Parser(context(), source).parse_module()
            bad.verify()
        except (VerifyException, ParseError) as error:
            errors[name] = {"exception": type(error).__name__, "diagnostic": str(error)}
        else:
            raise AssertionError(f"negative program accepted: {name}")
    (args.out / "before.mlir").write_text(before_text)
    (args.out / "after.mlir").write_text(after_text)
    version_probe = subprocess.run([str(args.entrypoint), "--version"], capture_output=True, text=True, timeout=60)
    assert version_probe.returncode == 0 and "0.74.0" in version_probe.stdout, version_probe
    cli = subprocess.run([str(args.entrypoint), str(args.out / "after.mlir")], capture_output=True, text=True, timeout=60)
    assert cli.returncode == 0, cli.stderr
    cli_module = Parser(context(), cli.stdout).parse_module()
    cli_module.verify()
    assert module.is_structurally_equivalent(cli_module)
    (args.out / "cli-roundtrip.mlir").write_text(cli.stdout)
    report = {
        "status": "passed", "xdsl_version": "0.74.0",
        "custom_operation": "cpg.double: (i32) -> i32",
        "rewrite": "cpg.double(x) -> arith.addi(x, x)",
        "entrypoint_version": version_probe.stdout.strip(), "entrypoint_parse_print_roundtrip": True,
        "parse_print_roundtrip": True, "verify_before_after": True,
        "rewrite_changed_ir": True, "rewrite_idempotent": True,
        "input_cases": len(values), "before": before, "after": after, "expected": expected,
        "negative_cases": errors,
        "scope": "Pure wrapping i32 example; not whole-framework correctness or target hardware evidence.",
        "upstream_declared_mlir_version": "22.1.2",
        "external_mlir_interoperation_executed": False,
    }
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Acceptance checks must not run with Python -O")
    main()
