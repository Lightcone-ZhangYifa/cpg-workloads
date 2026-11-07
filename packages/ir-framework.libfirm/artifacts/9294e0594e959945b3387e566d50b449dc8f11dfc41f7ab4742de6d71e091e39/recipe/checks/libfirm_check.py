#!/usr/bin/env python3
"""Generate and execute code from hand-built libFirm IR, preserving command evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include", type=Path, action="append", required=True)
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--upstream-tests", type=Path)
    ap.add_argument("--cc", default=os.environ.get("CC", "cc"))
    args = ap.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    records = []
    def run(command):
        p = subprocess.run([str(x) for x in command], cwd=args.out, text=True, capture_output=True, timeout=120)
        record = {"argv": [str(x) for x in command], "exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
        records.append(record)
        (args.out / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
        assert p.returncode == 0, record
        return p
    library = args.library.resolve()
    run([args.cc, "-std=c99", "-Wall", "-Wextra", "-Werror", *["-I" + str(p.resolve()) for p in args.include],
         here / "libfirm_generate.c", library, "-lm", "-o", "generate"])
    run([args.out / "generate", args.out / "generated.s"])
    assert (args.out / "generated.s").stat().st_size > 0
    # GNU-stack is controlled by the host link step; do not modify upstream IR/codegen.
    run([args.cc, "-no-pie", "-Wl,-z,noexecstack", here / "libfirm_driver.c", args.out / "generated.s", "-o", "generated-program"])
    executed = run([args.out / "generated-program"])
    expected = "-17 -> -46\n-1 -> 2\n0 -> 5\n1 -> 8\n21 -> 68\n100000 -> 300005\n"
    assert executed.stdout == expected
    unit_results = []
    if args.upstream_tests:
        names = ["deq", "globalmap", "nan_payload", "rbitset", "sc_val_from_bits", "snprintf", "strcalc", "tarval_calc", "tarval_float", "tarval_floatops", "tarval_from_to", "tarval_is_long"]
        for name in names:
            binary = args.upstream_tests.resolve() / (name + ".exe")
            result = run([binary])
            unit_results.append({"name": name, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    report = {
        "status": "passed", "libfirm_commit": "9107be1e1035dae7e509fce6abdbd7a1e8a83565",
        "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "target": "x86_64-linux-gnu", "generator": "checks/libfirm_generate.c",
        "direct_ir": "int cpg_affine(int x) { return x * 3 + 5; }",
        "graph_verify": True, "generated_assembly_sha256": hashlib.sha256((args.out / "generated.s").read_bytes()).hexdigest(),
        "input_cases": 6, "stdout": executed.stdout, "upstream_tests": unit_results,
        "limits": ["Finite bounded integer example; no general semantic-equivalence proof", "Only x86-64 codegen executed", "Host C compiler/assembler/linker/libc are required", "GNU-stack marker is absent in emitted assembly; host link explicitly uses -z noexecstack"],
    }
    (args.out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Acceptance checks must not run with Python -O")
    main()
