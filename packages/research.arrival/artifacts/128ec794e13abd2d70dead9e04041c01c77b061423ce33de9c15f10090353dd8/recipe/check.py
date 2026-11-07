#!/usr/bin/env python3
"""Run the frozen Arrival AArch64 rule chain and a semantic mutation control."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(str(message))


def run(binary, source, solver, work, name):
    out = work / name
    out.mkdir(parents=True)
    generated = out / "generated"
    generated.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(solver) + os.pathsep + "/usr/bin:/bin"
    cmd = [str(binary), "--name", "aarch64", "--codegen-crate-dir", str(source),
           "--work-dir", str(generated), "--filter", "rule:iadd_base_case",
           "--solver", "cvc5", "--timeout", "20", "--num-threads", "1",
           "--log-dir", str(out / "solver"), "--results-to-log-dir"]
    start = time.monotonic()
    p = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=240)
    (out / "console.log").write_text(p.stdout)
    (out / "invocation.json").write_text(json.dumps({"argv": cmd, "returncode": p.returncode,
        "elapsed_seconds": time.monotonic() - start}, indent=2) + "\n")
    return p, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    args = ap.parse_args()
    prefix = args.prefix.resolve()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    binary = prefix / "bin/arrival-veri"
    solver = prefix / "solver/bin"
    archive = prefix / "source/arrival-9b1765ab550810602cee8542eed9077274305632.tar.gz"
    require(sha(archive) == "8ef808746806c822d0056560b56094bf23f311cfb2f3c45e1dcfd2d886033551", "Upstream archive changed")
    source = work / "codegen"
    source.mkdir()
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 4 or parts[1:3] != ("cranelift", "codegen"):
                continue
            member.name = str(Path(*parts[3:]))
            stream.extract(member, source, filter="data")
    rule = source / "src/isa/aarch64/lower.isle"
    before = sha(rule)
    p, positive = run(binary, source, solver, work, "positive")
    require(p.returncode == 0, p.stdout[-4000:])
    report = json.loads((positive / "solver/report.json").read_text())
    require(len(report["expansions"]) == 1, "Expected one selected rule expansion")
    expansion = report["expansions"][0]
    expected_rules = ["iadd_base_case", "output_reg", "add_to_alu_rrr", "alu_rrr_to_emit"]
    require(expansion["rules"] == expected_rules, expansion["rules"])
    require(expansion["solver"] == "cvc5", "Solver identity changed")
    require(expansion["failed_type_inference"] == 0, "Type inference failed")
    results = {}
    for instance in expansion["type_instantiations"]:
        width = int(re.search(r"bv (\d+)", instance["choices"][0]).group(1))
        results[width] = instance["verify"]["verdict"]
    require(results == {8: "success", 16: "success", 32: "success", 64: "success", 128: "inapplicable"}, results)
    mutated = work / "mutated-codegen"
    shutil.copytree(source, mutated, symlinks=True)
    target = mutated / "src/isa/aarch64/lower.isle"
    old = "(rule iadd_base_case -1 (lower (has_type (fits_in_64 ty) (iadd _ x y)))\n      (add ty  x y))"
    new = old.replace("(add ty  x y)", "(sub ty  x y)")
    text = target.read_text()
    require(text.count(old) == 1, "Mutation target changed")
    target.write_text(text.replace(old, new))
    p, negative = run(binary, mutated, solver, work, "negative")
    require(p.returncode != 0 and "verification failed" in p.stdout, p.stdout[-4000:])
    values = re.findall(r"lower\(#x([0-9a-fA-F]+)\) -> #x([0-9a-fA-F]+)", p.stdout)
    require(any(int(a, 16) != int(b, 16) for a, b in values), "No semantic counterexample printed")
    require(sha(rule) == before, "Original source changed")
    summary = {"status": "passed", "resource": "arrival", "profile": "AArch64 iadd_base_case rule chain",
        "upstream_commit": "9b1765ab550810602cee8542eed9077274305632", "solver": "cvc5 1.2.0",
        "positive_widths": [8, 16, 32, 64], "inapplicable_widths": [128], "rules": expected_rules,
        "negative": "add-to-sub mutation rejected with unequal result counterexample",
        "rule_sha256": before, "mutated_rule_sha256": sha(target),
        "binary_sha256": sha(binary), "solver_sha256": sha(solver / "cvc5")}
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
