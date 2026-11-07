#!/usr/bin/env python3
"""Compile and execute C99 positive fixtures and require negative diagnostics."""
import argparse
import json
import os
from pathlib import Path
import subprocess

POSITIVE = r'''
extern int printf(const char *restrict format, ...);
struct pair { int x; int y; };
static inline int dot(int n, const int *restrict a, const int *restrict b)
{
    int result = 0;
    for (int i = 0; i < n; ++i) result += a[i] * b[i];
    return result;
}
int main(void)
{
    int n = 3;
    int values[n];
    for (int i = 0; i < n; ++i) values[i] = i + 1;
    int weights[3] = {[0] = 3, [1] = 2, [2] = 1};
    struct pair p = (struct pair){.y = 7, .x = 2};
    _Bool correct = dot(n, values, weights) == 10;
    printf("%d %d %d\n", dot(n, values, weights), p.x + p.y, (int)correct);
    return correct ? 0 : 2;
}
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cparser", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cc", default=os.environ.get("CC", "cc"))
    args = ap.parse_args()
    args.cparser = args.cparser.resolve()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    commands = []
    def run(command, expected_code=0):
        p = subprocess.run([str(x) for x in command], cwd=args.out, text=True, capture_output=True, timeout=120)
        record = {"argv": [str(x) for x in command], "exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
        commands.append(record)
        (args.out / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if expected_code is not None:
            assert p.returncode == expected_code, record
        return p
    (args.out / "positive-c99.c").write_text(POSITIVE)
    expected = "10 9 1\n"
    results = []
    for compiler_name, compiler in [("cparser", str(args.cparser)), ("host-cc", args.cc)]:
        for opt in ["-O0", "-O2"]:
            # Keep codegen, assembler, and system-linker evidence separate.
            assembly = args.out / f"{compiler_name}-{opt[1:]}.s"
            executable = args.out / f"{compiler_name}-{opt[1:]}"
            run([compiler, "-std=c99", "-m64", opt, "-S", "positive-c99.c", "-o", assembly])
            run([args.cc, "-no-pie", assembly, "-o", executable])
            executed = run([executable])
            assert executed.stdout == expected
            results.append({"compiler": compiler_name, "optimization": opt, "stdout": executed.stdout})
    # Exercise cparser's own full compile/link driver as well as the explicit phases.
    driver = run([args.cparser, "-std=c99", "-m64", "-O2", "positive-c99.c", "-Wl,-no-pie", "-o", "driver-program"])
    assert run([args.out / "driver-program"]).stdout == expected
    negatives = {
        "syntax_error": "int main(void) { return ; missing token }\n",
        "undeclared_identifier": "int main(void) { return unknown_variable + 1; }\n",
        "incompatible_redeclaration": "int f(int a); double f(int a); int main(void) { return 0; }\n",
        "duplicate_case": "int main(void) { int x = 0; switch(x) { case 1: return 1; case 1: return 2; } return 0; }\n",
    }
    diagnostics = {}
    for name, source in negatives.items():
        filename = args.out / f"{name}.c"
        filename.write_text(source)
        result = run([args.cparser, "-std=c99", "-m64", "-fsyntax-only", filename], expected_code=None)
        assert result.returncode != 0 and result.stderr
        diagnostics[name] = {"exit_code": result.returncode, "diagnostic": result.stderr}
    # Preserve a discovered valid-C99 limitation rather than hide it by shrinking
    # the positive fixture and claiming complete C99 support.
    valid_vla_parameter = "int sum(int n, const int a[restrict static n]) { return a[0]; }\n"
    (args.out / "valid-c99-vla-parameter.c").write_text(valid_vla_parameter)
    reference = run([args.cc, "-std=c99", "-pedantic-errors", "-fsyntax-only", "valid-c99-vla-parameter.c"])
    observed = run([args.cparser, "-std=c99", "-m64", "-fsyntax-only", "valid-c99-vla-parameter.c"], expected_code=None)
    assert observed.returncode != 0 and "'n' is unknown" in observed.stderr
    report = {
        "status": "passed", "cparser_commit": "81330da3ee9650c88a1afdc93de654b9dfd9fb78",
        "paired_libfirm_commit": "9107be1e1035dae7e509fce6abdbd7a1e8a83565", "target": "x86_64-linux-gnu",
        "source_build": True, "positive_executions": results,
        "full_driver_compile_link_run": True, "negative_cases": diagnostics,
        "features_exercised": ["C99 for-loop declarations", "variable-length automatic array", "restrict pointer parameter", "inline function", "designated initializer", "compound literal", "_Bool"],
        "known_valid_c99_rejection": {"feature": "VLA parameter bound referencing preceding parameter", "host_cc_exit_code": reference.returncode, "cparser_exit_code": observed.returncode, "diagnostic": observed.stderr},
        "limits": ["Finite smoke suite, not complete C99 conformance", "No C++ claim", "No claim for untested backends", "Host assembler, libc and linker are platform prerequisites"],
        "version_output": run([args.cparser, "--version"]).stdout,
    }
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Acceptance checks must not run with Python -O")
    main()
