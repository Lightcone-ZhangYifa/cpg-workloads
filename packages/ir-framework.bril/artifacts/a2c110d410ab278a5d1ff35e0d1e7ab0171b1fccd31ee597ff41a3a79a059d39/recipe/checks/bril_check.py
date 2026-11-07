#!/usr/bin/env python3
"""Exercise the unchanged Bril reference interpreter and upstream TDCE pass."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys


def const(dest, value, typ="int"):
    return {"op": "const", "dest": dest, "type": typ, "value": value}


def value(op, dest, args, typ="int"):
    return {"op": op, "dest": dest, "type": typ, "args": args}


def program(instrs):
    return {"functions": [{"name": "main", "args": [{"name": "n", "type": "int"}], "instrs": instrs}]}


FIXTURES = {
    "arithmetic": (
        program([const("dead", 7), value("mul", "dead2", ["dead", "dead"]), const("two", 2),
                 value("mul", "answer", ["n", "two"]), {"op": "print", "args": ["answer"]}]),
        [-17, 0, 1, 21], lambda n: f"{2*n}\n"),
    "branch": (
        program([const("zero", 0), const("unused", 99), value("lt", "negative", ["n", "zero"], "bool"),
                 {"op": "br", "args": ["negative"], "labels": ["neg", "nonneg"]},
                 {"label": "neg"}, value("sub", "absolute", ["zero", "n"]),
                 {"op": "print", "args": ["absolute"]}, {"op": "jmp", "labels": ["done"]},
                 {"label": "nonneg"}, {"op": "print", "args": ["n"]}, {"label": "done"}, {"op": "ret"}]),
        [-17, 0, 1, 21], lambda n: f"{abs(n)}\n"),
    "loop": (
        program([const("sum", 0), const("i", 0), const("one", 1), const("unused", 99),
                 {"label": "loop"}, value("lt", "keep", ["i", "n"], "bool"),
                 {"op": "br", "args": ["keep"], "labels": ["body", "done"]}, {"label": "body"},
                 value("add", "sum", ["sum", "i"]), value("add", "i", ["i", "one"]),
                 {"op": "jmp", "labels": ["loop"]}, {"label": "done"}, {"op": "print", "args": ["sum"]}]),
        [0, 1, 5, 10], lambda n: f"{n*(n-1)//2}\n"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--deno", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.source = args.source.resolve()
    args.deno = args.deno.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(DENO_DIR=str(args.out.resolve() / "deno-cache"), DENO_NO_UPDATE_CHECK="1", NO_COLOR="1")
    cmd = [str(args.deno), "run", "--cached-only", "--deny-net", "--no-prompt", str(args.source / "brili.ts")]
    def run(source, inputs=()):
        return subprocess.run(cmd + [str(i) for i in inputs], input=json.dumps(source), text=True,
                              capture_output=True, env=env, timeout=20)
    rows = []
    mutant_rejected = False
    for name, (before, inputs, expected) in FIXTURES.items():
        transformed = subprocess.run([sys.executable, str(args.source / "examples/tdce.py")],
                                     input=json.dumps(before), capture_output=True, text=True, timeout=20)
        assert transformed.returncode == 0, transformed.stderr
        after = json.loads(transformed.stdout)
        before_count = len(before["functions"][0]["instrs"])
        after_count = len(after["functions"][0]["instrs"])
        assert after_count < before_count, (name, before_count, after_count)
        (args.out / f"{name}-before.json").write_text(json.dumps(before, indent=2) + "\n")
        (args.out / f"{name}-after.json").write_text(json.dumps(after, indent=2) + "\n")
        case_results = []
        for n in inputs:
            original, optimized = run(before, [n]), run(after, [n])
            assert original.returncode == optimized.returncode == 0, (original.stderr, optimized.stderr)
            assert original.stdout == optimized.stdout == expected(n)
            case_results.append({"input": n, "before_stdout": original.stdout, "after_stdout": optimized.stdout,
                                 "before_stderr": original.stderr, "after_stderr": optimized.stderr})
        rows.append({"name": name, "before_instruction_entries": before_count,
                     "after_instruction_entries": after_count, "cases": case_results})
        if name == "arithmetic":
            mutant = copy.deepcopy(after)
            mutant["functions"][0]["instrs"] = [i for i in mutant["functions"][0]["instrs"] if i["op"] != "print"]
            observed = run(mutant, [21])
            mutant_rejected = observed.stdout != expected(21)
            assert observed.returncode == 0 and mutant_rejected
    negatives = {
        "undefined_variable": {"functions": [{"name": "main", "instrs": [{"op": "print", "args": ["not_defined"]}]}]},
        "wrong_operand_count": {"functions": [{"name": "main", "instrs": [const("x", 1), value("add", "y", ["x"])]}]},
    }
    negative_results = {}
    for name, source in negatives.items():
        result = run(source)
        assert result.returncode != 0, (name, result.stdout, result.stderr)
        negative_results[name] = {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    version = subprocess.run([str(args.deno), "--version"], text=True, capture_output=True, check=True).stdout
    report = {
        "status": "passed", "bril_commit": "e8b05b703acc9601addd6053294a3040863194cc",
        "interpreter": "Unmodified upstream brili.ts", "pass": "Unmodified upstream examples/tdce.py",
        "runtime_version": version, "runtime_network_policy": "--cached-only --deny-net --no-prompt",
        "programs": rows, "equivalence_cases": sum(len(r["cases"]) for r in rows),
        "negative_programs": negative_results, "output_mutant_rejected_by_oracle": mutant_rejected,
        "scope": "Bounded well-typed core integer/boolean fixtures only; upstream educational TDCE is not validated for side-effecting value instructions, memory, traps, floating point or arbitrary programs.",
    }
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Acceptance checks must not run with Python -O")
    main()
