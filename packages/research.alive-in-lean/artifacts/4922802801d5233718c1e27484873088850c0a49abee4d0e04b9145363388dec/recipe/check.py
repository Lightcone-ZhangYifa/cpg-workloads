#!/usr/bin/env python3
"""Offline preparation and bounded replay of the original AliveInLean verifier."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile

COMMIT = "4b739dd6e4266b26a045613849df221374119871"
MATHLIB = "019b2364cadb1dd8b30c9f13c602d61c19d3b6ea"
SMT = "7ff0ce248b68ea4db2a2d4966a97b5786da05ed7"
PROBE = "import src.spec.refinement\n#check spec.refines_single_reg_correct_prf\n#print axioms spec.refines_single_reg_correct_prf\n"
THEOREM_TYPE = "spec.refines_single_reg_correct_prf : spec.refines_single_reg_correct"
EXPECTED_AXIOMS = ["propext", "classical.choice", "quot.sound", "[sorry]"]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def theorem_axioms(record):
    """Check the complete axiom list, including any previously unknown axiom."""
    if record["stderr"].strip() or "error:" in record["stdout"]:
        raise RuntimeError("Unexpected verifier theorem diagnostic")
    lines = [line.strip() for line in record["stdout"].splitlines() if line.strip()]
    if lines.count(THEOREM_TYPE) != 1:
        raise RuntimeError("The fixed verifier theorem was not uniquely loaded")
    type_index = lines.index(THEOREM_TYPE)
    if any("warning: imported file " not in line or not line.endswith("uses sorry") for line in lines[:type_index]):
        raise RuntimeError("Unexpected output before the verifier theorem declaration")
    axioms = lines[type_index + 1:]
    if axioms != EXPECTED_AXIOMS:
        raise RuntimeError("The complete theorem axiom boundary differs from the frozen upstream: " + repr(axioms))
    return axioms


def environment(prefix):
    env = dict(os.environ)
    env.pop("LEAN_PATH", None)
    env["PATH"] = str(prefix / "tools/lean/bin") + os.pathsep + str(prefix / "tools/z3/bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@contextmanager
def replay_tree(prefix, output):
    """Give historical Lean a byte-identical cache with coherent dependency times.

    Lean 3.4.2 invalidates an olean when a transitive dependency has a newer
    timestamp. Archive installers may create files in a different order than
    the original compilation. Normalize timestamps only in a private copy;
    never modify the installed prefix or replace checked compiler output.
    """
    with tempfile.TemporaryDirectory(prefix="alive-replay-", dir=output) as td:
        work = Path(td)
        records = []
        for source_rel, destination_rel in (("project", "project"), ("tools/lean/lib/lean/library", "library")):
            source, destination = prefix / source_rel, work / destination_rel
            expected = {p.relative_to(source).as_posix(): {"sha256": digest(p), "bytes": p.stat().st_size}
                        for p in sorted(source.rglob("*")) if p.is_file()}
            if not expected:
                raise RuntimeError("Missing frozen Lean replay input: " + source_rel)
            shutil.copytree(source, destination)
            copied = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
            if copied != set(expected):
                raise RuntimeError("Replay copy inventory differs: " + source_rel)
            for name, entry in expected.items():
                original, target = source / name, destination / name
                if digest(original) != entry["sha256"] or digest(target) != entry["sha256"] or target.stat().st_size != entry["bytes"]:
                    raise RuntimeError("Replay copy changed bytes: " + source_rel + "/" + name)
                mtime = 1 if target.suffix == ".lean" else 2 if target.suffix == ".olean" else None
                if mtime is not None:
                    os.utime(target, (mtime, mtime))
                if digest(target) != entry["sha256"]:
                    raise RuntimeError("Cache timestamp normalization changed bytes: " + name)
                records.append({"source": source_rel + "/" + name,
                                "copy": destination_rel + "/" + name,
                                **entry, "normalized_mtime": mtime})
        project = work / "project"
        paths = [work / "library", project / "_target/deps/mathlib",
                 project / "_target/deps/smt2_interface/src", project]
        env = environment(prefix)
        env["LEAN_PATH"] = os.pathsep.join(str(p) for p in paths)
        report = {"schema_version": 1, "status": "byte-identical-isolated-cache",
                  "files": records, "file_count": len(records),
                  "bytes": sum(item["bytes"] for item in records),
                  "lean_path": [str(p) for p in paths], "installed_prefix_modified": False,
                  "source_mtime": 1, "compiled_cache_mtime": 2,
                  "reason": "Lean 3.4.2 module_mgr.cpp rebuilds an olean if a transitive dependency is newer. Normalize only byte-verified copies so archive extraction order cannot invalidate the frozen binary cache."}
        (output / "cache-replay-tree.json").write_text(json.dumps(report, indent=2) + "\n")
        path_record = run([prefix / "tools/lean/bin/lean", "--path"], project, env, output, "lean-search-path", timeout=60)
        effective_paths = json.loads(path_record["stdout"])["path"]
        if effective_paths != [str(p) for p in paths]:
            raise RuntimeError("Lean search path escaped the four isolated replay directories")
        yield project, env


def run(cmd, cwd, env, output, label, timeout=900):
    start = time.monotonic()
    try:
        result = subprocess.run([str(x) for x in cmd], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        record = {"argv": [str(x) for x in cmd], "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "seconds": time.monotonic() - start}
    except subprocess.TimeoutExpired as e:
        record = {"argv": [str(x) for x in cmd], "returncode": None, "timeout": True, "stdout": (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "stderr": (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or ""), "seconds": time.monotonic() - start}
    (output / (label + ".json")).write_text(json.dumps(record, indent=2) + "\n")
    (output / (label + ".log")).write_text(record["stdout"] + record["stderr"])
    if record["returncode"] != 0:
        raise RuntimeError(label + " failed; see " + str(output / (label + ".log")))
    return record


def extract_tar(archive, parent, expected, target):
    with tempfile.TemporaryDirectory(prefix="unpack-", dir=parent) as td:
        with tarfile.open(archive) as t:
            t.extractall(td, filter="data")
        source = Path(td) / expected
        if not source.is_dir():
            raise RuntimeError("Missing expected archive root: " + expected)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)


def prepare(payload, prefix, output):
    lock = json.loads((payload / "inputs.lock.json").read_text())
    for item in lock["files"]:
        path = payload / item["file"]
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise RuntimeError("Input hash mismatch: " + item["file"])
    prefix.mkdir(parents=True, exist_ok=True)
    if (prefix / "project").exists():
        raise RuntimeError("Destination already contains a project; use a fresh prefix")
    extract_tar(payload / ("raw/AliveInLean-" + COMMIT + ".tar.gz"), prefix, "AliveInLean-" + COMMIT, prefix / "project")
    extract_tar(payload / ("raw/mathlib-" + MATHLIB + ".tar.gz"), prefix, "mathlib3-" + MATHLIB, prefix / "project/_target/deps/mathlib")
    extract_tar(payload / ("raw/smt2_interface-" + SMT + ".tar.gz"), prefix, "smt2_interface-" + SMT, prefix / "project/_target/deps/smt2_interface")
    extract_tar(payload / "raw/lean-3.4.2-linux.tar.gz", prefix, "lean-3.4.2-linux", prefix / "tools/lean")
    z3 = prefix / "tools/z3"
    (z3 / "bin").mkdir(parents=True)
    with zipfile.ZipFile(payload / "raw/z3-4.8.7-x64-ubuntu-16.04.zip") as z:
        (z3 / "bin/z3").write_bytes(z.read("z3-4.8.7-x64-ubuntu-16.04/bin/z3"))
        (z3 / "LICENSE.txt").write_bytes(z.read("z3-4.8.7-x64-ubuntu-16.04/LICENSE.txt"))
    (z3 / "bin/z3").chmod(0o755)
    shutil.copytree(payload / "licenses", prefix / "licenses")
    shutil.copyfile(payload / "inputs.lock.json", prefix / "inputs.lock.json")
    env = environment(prefix)
    compiled = []
    for module, label in [("src/main.lean", "compile-main"), ("src/spec/refinement.lean", "compile-theorem")]:
        result = run([prefix / "tools/lean/bin/lean", "--make", "-j", "1", "--memory=512", module], prefix / "project", env, output, label, timeout=1200)
        if "error:" in result["stdout"] + result["stderr"]:
            raise RuntimeError("Lean emitted a source compilation error")
        compiled.append(result)
    for name in ("src/main.olean", "src/spec/refinement.olean"):
        if not (prefix / "project" / name).is_file():
            raise RuntimeError("Missing compiled module: " + name)
    build_evidence = prefix / "build-evidence"
    build_evidence.mkdir()
    (build_evidence / "compile.log").write_text("\n".join(r["stdout"] + r["stderr"] for r in compiled))
    receipt = {"upstream_commit": COMMIT, "source_compile_returncode": 0, "compiler_invocations": [{"argv": r["argv"], "returncode": r["returncode"], "seconds": r["seconds"]} for r in compiled], "compile_log_sha256": digest(build_evidence / "compile.log"), "inputs": lock["files"], "compiled_tree": {str(f.relative_to(prefix)): digest(f) for f in sorted((prefix / "project").rglob("*")) if f.is_file() and f.suffix in (".lean", ".olean")}}
    (build_evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return {"prepared": True, "source_compile": True, "network_used": False}


def verify(prefix, output):
    lean = prefix / "tools/lean/bin/lean"
    receipt = json.loads((prefix / "build-evidence/receipt.json").read_text())
    if receipt.get("source_compile_returncode") != 0 or receipt.get("upstream_commit") != COMMIT:
        raise RuntimeError("Missing successful source compilation receipt for the pinned verifier")
    if digest(prefix / "build-evidence/compile.log") != receipt["compile_log_sha256"]:
        raise RuntimeError("Source compilation evidence changed")
    for name, expected_hash in receipt["compiled_tree"].items():
        if digest(prefix / name) != expected_hash:
            raise RuntimeError("Prepared source/module changed: " + name)
    checks = []
    with replay_tree(prefix, output) as (project, env):
        for filename, expected in [("opt001", "Incorrect"), ("opt002", "Correct")]:
            result = run([lean, "-q", "--run", "src/main.lean", "-verifyopt", "inputs/alive/unit/" + filename, "-verbose"], project, env, output, filename, timeout=180)
            lines = result["stdout"].splitlines()
            if not lines or lines[-1] != expected:
                raise RuntimeError("Unexpected verifier decision for " + filename)
            solver_lines = [line for line in lines if line in ("sat", "unsat", "unknown")]
            if solver_lines != ["unsat" if expected == "Correct" else "sat"]:
                raise RuntimeError("Unexpected SMT result for " + filename + ": " + repr(solver_lines))
            checks.append({"case": filename, "expected": expected, "passed": True})
        with tempfile.TemporaryDirectory(prefix="alive-theorem-", dir=output) as td:
            probe = Path(td) / "TheoremAudit.lean"
            probe.write_text(PROBE)
            result = run([lean, "-j", "1", "--memory=768", probe], project, env, output, "theorem-axioms", timeout=300)
        axioms = theorem_axioms(result)
    checks.append({"case": "verifier-theorem", "passed": True, "axioms": axioms, "axioms_report": "theorem-axioms.log", "source_compile_receipt": "build-evidence/receipt.json", "upstream_admitted_overflow_lemmas": 4})
    result = {"status": "passed", "resource_id": "verification.alive-in-lean", "checks": checks, "scope": "Pinned Lean 3.4.2 source elaboration, official correct/incorrect i4 rules, and verifier theorem with upstream assumptions retained.", "no_claims": ["SMT solver proved sound", "Four upstream admitted overflow lemmas proved", "LLVM whole-program equivalence"]}
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "verify"])
    parser.add_argument("--payload", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prefix, output = args.prefix.resolve(), args.output.resolve()
    if output == prefix or prefix in output.parents:
        raise ValueError("Evidence output must be outside the installed prefix")
    output.mkdir(parents=True, exist_ok=True)
    result = prepare(args.payload.resolve(), prefix, output) if args.action == "prepare" else verify(prefix, output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
