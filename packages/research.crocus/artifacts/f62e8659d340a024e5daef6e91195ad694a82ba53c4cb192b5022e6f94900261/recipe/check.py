#!/usr/bin/env python3
"""Replay the author's fixed Crocus rule group and CVE counterexample offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import tarfile
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()
    prefix, work = args.prefix.resolve(), args.work.resolve()
    require(not work.exists(), "--work must be a fresh directory")
    require(not work.is_relative_to(prefix), "--work must be outside the immutable prefix")
    work.mkdir(parents=True)
    (work / "tmp").mkdir()
    (work / "home").mkdir()
    lock = json.loads((prefix / "provenance/profile-lock.json").read_text())
    for relative, expected in lock["checked_files"].items():
        require(digest(prefix / relative) == expected, f"Pinned input differs: {relative}")
    archive = prefix / "source/crocus.tar.gz"
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        tops = {Path(member.name).parts[0] for member in members if Path(member.name).parts}
        require(len(tops) == 1, "Unexpected source archive structure")
        for member in members:
            path = Path(member.name)
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe source path")
            # The verifier uses ordinary source files. The untouched archive
            # remains available; optional nonregular repository entries are
            # not needed by, or followed during, this runtime materialization.
            destination = work / "source" / path
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as stream, destination.open("wb") as output:
                    shutil.copyfileobj(stream, output)
                destination.chmod(member.mode & 0o777)
    root = work / "source" / next(iter(tops))
    cwd = root / "cranelift/isle/veri/veri_engine"
    require(cwd.is_dir(), "Missing upstream verifier fixture directory")
    env = os.environ.copy()
    env.pop("SKIP_SOLVER", None)
    env.update(PATH=f"{prefix}/tools/z3/bin:/usr/bin:/bin", LC_ALL="C",
               HOME=str(work / "home"), TMPDIR=str(work / "tmp"), RUST_BACKTRACE="1")
    tests = [
        ("positive-iadd-group", ["test_named_iadd_base", "test_named_iadd_imm12_left",
                                 "test_named_iadd_imm12_right"]),
        ("negative-author-cve", ["test_broken_imm_udiv_cve_underlying_32"]),
    ]
    results = []
    memory_limit = 1024 * 1024 * 1024

    def bounded():
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    for name, names in tests:
        command = [str(prefix / "bin/crocus-veri-tests"), "--exact", "--nocapture",
                   "--test-threads=1", *names]
        started = time.monotonic()
        with (work / f"{name}.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, preexec_fn=bounded,
                                       start_new_session=True)
            try:
                returncode = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                returncode = 124
        record = dict(profile=name, tests=names, returncode=returncode,
                      elapsed_seconds=time.monotonic() - started)
        results.append(record)
        (work / "process-results.json").write_text(json.dumps(results, indent=2) + "\n")
        require(returncode == 0, f"Upstream {name} failed; inspect its log")
    positive = (work / "positive-iadd-group.log").read_text(errors="replace")
    negative = (work / "negative-author-cve.log").read_text(errors="replace")
    require("test result: ok. 3 passed; 0 failed; 0 ignored;" in positive,
            "Positive rule group was not actually executed")
    require(positive.count("Verification succeeded") == 12,
            "Expected three original rules at all four widths")
    require("Verification failed" not in positive, "Unexpected failing positive rule")
    require("test result: ok. 1 passed; 0 failed; 0 ignored;" in negative,
            "Author negative test was not actually executed")
    require("Expected result: Failure(Counterexample)" in negative,
            "Wrong negative-test oracle")
    require("Verification failed" in negative and "Counterexample summary" in negative,
            "No genuine verifier counterexample")
    values = re.search(r"(?m)^(#x[0-9a-fA-F]+)\|0b[01]+\s*=>\s*\n(#x[0-9a-fA-F]+)\|0b[01]+", negative)
    require(values is not None, "No concrete LHS/RHS counterexample values")
    lhs, rhs = values.groups()
    require(int(lhs[2:], 16) != int(rhs[2:], 16), "Counterexample results must differ")
    summary = dict(passed=True, scope="AArch64 iadd rule group and author udiv CVE case",
                   artifact_commit=lock["artifact_commit"], implementation_commit=lock["implementation_commit"],
                   solver=lock["solver"], rules=["iadd_base_case", "iadd_imm12_left", "iadd_imm12_right"],
                   widths=[8, 16, 32, 64], proved_rule_width_pairs=12,
                   negative_test="test_broken_imm_udiv_cve_underlying_32",
                   counterexample={"lhs": lhs, "rhs": rhs}, processes=results,
                   memory_address_space_limit=memory_limit)
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
