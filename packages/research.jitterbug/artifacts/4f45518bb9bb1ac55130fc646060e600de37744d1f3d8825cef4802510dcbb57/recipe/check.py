#!/usr/bin/env python3
"""Run the frozen upstream RV64 ADD32 proof and its author-supplied bug mode.

This is an adapter to upstream Jitterbug/Serval/Rosette, not a replacement model.
The source installation is read-only; all process state and evidence go to --work.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def racket_path(path):
    return json.dumps(str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    work = args.work.resolve()
    require(not work.exists(), "--work must be a fresh directory")
    require(not work.is_relative_to(prefix), "--work must be outside the immutable prefix")
    require(args.timeout > 0, "timeout must be positive")
    work.mkdir(parents=True)
    for directory in ("home", "tmp"):
        (work / directory).mkdir()
    lock = json.loads((prefix / "provenance/profile-lock.json").read_text())
    for relative, expected in lock["checked_files"].items():
        require(digest(prefix / relative) == expected, f"Pinned input differs: {relative}")
    source = prefix / "src/jitterbug/racket"
    script = work / "profile.rkt"
    script.write_text(f'''#lang rosette
(require (file {racket_path(source / 'lib/tests.rkt')})
         (only-in (file {racket_path(source / 'riscv/rv64/spec.rkt')}) rv64-target)
         (only-in (file {racket_path(source / 'lib/spec/bpf.rkt')}) bpf-target)
         (only-in (file {racket_path(source / 'lib/spec/proof.rkt')}) verify-bpf-jit/64)
         (prefix-in riscv: serval/riscv/base)
         (prefix-in bpf: serval/bpf)
         serval/lib/unittest)
(file-stream-buffer-mode (current-output-port) 'line)
;; The only domain restriction is the instruction's register names. All
;; register VALUES and the stock preconditions remain symbolic and unchanged.
(define profile-target
  (struct-copy bpf-target rv64-target
    [select-bpf-regs (lambda (role) (if (eq? role 'dst) '(r0) '(r1)))]))
(define (check-jit-profile code)
  (parameterize ([riscv:XLEN 64])
    (verify-bpf-jit/64 code profile-target)))
(define positive
  (jit-verify "CPG RV64 ADD32 r0,r1 fixed upstream JIT" check-jit-profile verify-all
              '(BPF_ALU BPF_ADD BPF_X)))
(unless (zero? positive) (error "positive verification failed"))
(displayln "CPG_JITTERBUG_POSITIVE_UNSAT")
;; Exact upstream rv64/bugs.rkt predicate. The original checker deliberately
;; checks BPF's zero upper half; the actual bug is established by a SAT model
;; from verify/debug-proc, never by treating a crash as a counterexample.
(define (check-alu32 info)
  (define insn (dict-ref info 'bpf-insn))
  (define final-bpf-regs (dict-ref info 'final-bpf-regs))
  (define dst (bpf:insn-dst insn))
  (define dstval (bpf:@reg-ref final-bpf-regs dst))
  (check-equal? (extract 63 32 dstval) (bv 0 32))
  (printf "CPG_COUNTEREXAMPLE_INSN=~v\\n" insn)
  (printf "CPG_COUNTEREXAMPLE_INPUT_REGS=~v\\n" (dict-ref info 'bpf-regs))
  (printf "CPG_COUNTEREXAMPLE_BPF_DST=~v\\n" dstval))
(define negative
  (test-bugs "CPG RV64 author bug kernel 1e692f09e091" check-jit-profile
             ['(BPF_ALU BPF_ADD BPF_X) check-alu32]))
(unless (zero? negative) (error "author counterexample replay failed"))
(displayln "CPG_JITTERBUG_AUTHOR_BUG_REPLAY_PASSED")
''')
    env = os.environ.copy()
    env.update(PATH=f"{prefix}/tools/racket/bin:{prefix}/tools/z3/bin",
               HOME=str(work / "home"), PLTUSERHOME=str(work / "home"),
               TMPDIR=str(work / "tmp"), XDG_CACHE_HOME=str(work / "home/cache"),
               Z3=str(prefix / "tools/z3/bin/z3"), SOLVER="z3",
               ENABLE_JIT_SPLIT_REGS="1", ENABLE_STACK_ADDR_SYMOPT="1")
    for key in ("BOOLECTOR", "CVC4", "PLTCOLLECTS", "PLTCOMPILEDROOTS", "PLTADDONDIR"):
        env.pop(key, None)
    command = [str(prefix / "tools/racket/bin/racket"), str(script)]
    memory_limit = 1024 * 1024 * 1024

    def bounded():
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    started = time.monotonic()
    timed_out = False
    with (work / "proof.log").open("w") as stream:
        process = subprocess.Popen(command, cwd=work, env=env, stdout=stream,
                                   stderr=subprocess.STDOUT, preexec_fn=bounded,
                                   start_new_session=True)
        try:
            returncode = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            returncode = 124
    text = (work / "proof.log").read_text(errors="replace")
    model_lines = [line for line in text.splitlines() if line.startswith("CPG_COUNTEREXAMPLE_")]
    summary = dict(profile="rv64-add32-register-author-bug", returncode=returncode,
                   timed_out=timed_out, elapsed_seconds=time.monotonic() - started,
                   memory_address_space_limit=memory_limit,
                   architecture="RV64", instruction=["BPF_ALU", "BPF_ADD", "BPF_X"],
                   register_domain="dst=r0, src=r1; register values remain symbolic",
                   symbolic_operands=True, upstream_preconditions_unchanged=True,
                   source_commit=lock["jitterbug_commit"], serval_commit=lock["serval_commit"],
                   solver=lock["solver"], kernel_bug="1e692f09e091",
                   counterexample_lines=model_lines)
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    require(returncode == 0, f"Jitterbug failed or timed out; inspect {work / 'proof.log'}")
    require(text.count("CPG_JITTERBUG_POSITIVE_UNSAT") == 1, "Missing positive proof")
    require(text.count("CPG_JITTERBUG_AUTHOR_BUG_REPLAY_PASSED") == 1, "Missing author bug replay")
    require(len(re.findall(r"1 success\(es\) 0 failure\(s\) 0 error\(s\) 1 test\(s\) run", text)) == 2,
            "Expected exactly two passing upstream one-test suites")
    require("Failed assertions:" in text, "No upstream SAT-model failure was replayed")
    require("Final registers must match" in text,
            "The counterexample does not identify the expected register-equivalence failure")
    require(any(line.startswith("CPG_COUNTEREXAMPLE_BPF_DST=") for line in model_lines),
            "No concrete counterexample destination value")
    require("Using solver #<z3>" in text, "Unexpected solver")
    summary["passed"] = True
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
