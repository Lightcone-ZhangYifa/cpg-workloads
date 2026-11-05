#!/usr/bin/env python3
"""Probe the official CPG parser with DejaGNU source-produced output.

This is a reference-format test, NOT a GCC run and NOT an Expect installation.
The pinned framework.exp is evaluated by a Python/Tcl bridge.  Only its
output destinations are replaced.  All compiler/tool/process contexts below
are explicitly synthetic parser fixtures.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tkinter

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
STATUS = ("PASS", "FAIL", "XPASS", "XFAIL", "KPASS", "KFAIL",
          "UNRESOLVED", "UNTESTED", "UNSUPPORTED")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_fixture(boards: list[tuple[str, list[tuple[str, str]]]], *, warnings=False):
    source = ROOT / "source/dejagnu-1.6.3/lib/framework.exp"
    interpreter = tkinter.Tcl()
    output = []
    # clone_output chooses a channel; collect each call once.  No test status
    # or summary logic is replaced or reconstructed here.
    def capture(*args):
        output.append(str(args[-1]))
        return ""
    for channel in ("send_user", "send_log", "send_error"):
        interpreter.createcommand(channel, capture)
    interpreter.eval("proc verbose {args} {}")
    interpreter.call("source", str(source.resolve()))
    for key, value in {
        "xml": 0, "exit_status": 0, "xfail_flag": 0, "xfail_prms": 0,
        "kfail_flag": 0, "kfail_prms": 0, "multipass_name": "",
        "sum_file": "", "all_flag": 1, "tool": "gcc",
    }.items():
        interpreter.setvar(key, value)
    interpreter.call("init_testcounts")
    output.extend(["Test run by synthetic source-format probe\n",
                   "Native configuration is x86_64-pc-linux-gnu\n",
                   "\t\t=== gcc tests ===\n"])
    for board, events in boards:
        interpreter.setvar("current_target_name", board)
        interpreter.call("reset_vars")
        output.append(f"Running target {board}\n")
        output.append("Running /synthetic/tests/gcc.dg/dg.exp ...\n")
        if warnings:
            for index in range(3):
                interpreter.call("warning", f"synthetic framework warning {index}")
        for status, name in events:
            interpreter.call("record_test", status, name)
        if len(boards) > 1:
            interpreter.call("log_summary")
    interpreter.call("log_summary", "total")
    return "".join(output), {
        "tcl_patchlevel": interpreter.call("info", "patchlevel"),
        "source_framework_sha256": digest(source),
        "source_function_exit_status": int(interpreter.getvar("exit_status")),
        "counts": {status: int(interpreter.getvar(f"test_counts({status},total)"))
                   for status in STATUS},
        "output_channels_replaced": ["send_user", "send_log", "send_error"],
        "verbose": "no-op logging replacement",
        "runtest_exp_executed": False, "expect_executed": False,
    }


def context(count: int, failed=False) -> dict:
    return {
        "schema_version": 1, "run_id": "SYNTHETIC-dejagnu-parser-fixture",
        "compiler_revision": "SYNTHETIC-NO-COMPILER-WAS-EXECUTED",
        "build": "x86_64-pc-linux-gnu", "host": "x86_64-pc-linux-gnu",
        "target": "x86_64-pc-linux-gnu", "languages": ["c"],
        "suite_profile": "synthetic-source-format-only", "board": "unix",
        "multilib": "synthetic", "configuration": {"synthetic": True},
        "selection": {"scope": "source-format-fixture"},
        "tool_identity_profile": {"compiler": "not executed"},
        "harness": {"name": "dejagnu", "version": "synthetic-context-for-1.6.3-output",
                    "identity": digest(ROOT / "source/dejagnu-1.6.3/lib/framework.exp"),
                    "test_failure_exit_codes": [1],
                    "exit_code_evidence": "Source framework.exp record_test sets exit_status=1 for FAIL, XPASS, KPASS, UNRESOLVED; no runtest process claimed."},
        "invocation": {"argv": ["SYNTHETIC-PARSER-FIXTURE"], "effective_options": [],
                       "environment": {key: None for key in ("DEJAGNU", "RUNTESTFLAGS", "LC_ALL", "LANG")}},
        "completion": {"state": "completed", "evidence": "SYNTHETIC source-format fixture, not an execution attestation",
                       "expected_outcomes": count, "unreported_selected_tests": 0,
                       "returncode": 1 if failed else 0, "signal": None,
                       "process_outcome": "test-failures" if failed else "success",
                       "harness_errors": [],
                       "test_failure_evidence": "SYNTHETIC known-failure fixture" if failed else None},
        "path_prefixes": {"/synthetic/tests": "$TESTS"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpg-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/source-parser-probe.json")
    args = parser.parse_args()
    (ROOT / "evidence").mkdir(exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.cpg_root.resolve()))
    from compiler_playground.upstream_results import parse_dejagnu_sum

    fixtures = ROOT / "fixtures"
    fixtures.mkdir(exist_ok=True)
    positive, positive_trace = source_fixture([("unix", [("PASS", "repeated identity"), ("PASS", "repeated identity"), ("XFAIL", "known expected failure")])])
    mixed, mixed_trace = source_fixture([("unix", [(code, f"synthetic {code}") for code in STATUS])])
    boards, board_trace = source_fixture([("unix/-m32", [("PASS", "shared name")]), ("unix/-m64", [("PASS", "shared name")])])
    warning, warning_trace = source_fixture([("unix", [("PASS", "must become UNRESOLVED")])], warnings=True)
    empty, empty_trace = source_fixture([("unix", [])])

    case_specs = [
        ("source-positive", positive, context(3), True, True, None),
        ("source-all-nine-statuses", mixed, context(9, True), True, False, None),
        ("source-two-boards", boards, context(2), True, True, None),
        ("missing-controller-context", positive, None, False, False, "completion_missing"),
        ("truncated-before-summary", positive.split("=== gcc Summary ===")[0], context(3), False, False, "summary_missing"),
        ("duplicate-summary-count", positive + "# of expected passes\t2\n", context(3), False, False, "duplicate_summary_count"),
        ("negative-summary-count", positive.replace("# of expected passes\t\t2", "# of expected passes\t-2"), context(3), False, False, "malformed_summary"),
        ("unknown-outcome", positive.replace("PASS: repeated identity", "ALIEN: repeated identity", 1), context(3), False, False, "unknown_status"),
        ("missing-outcome", positive.replace("PASS: repeated identity\n", "", 1), context(3), False, False, "summary_mismatch"),
        ("duplicate-final-summary", positive + positive[positive.index("\n\t\t=== gcc Summary ==="):], context(3), False, False, "duplicate_total_summary"),
        ("source-empty-summary", empty, context(0), False, False, "empty_results"),
        ("source-warning-threshold", warning, context(4, True), False, False, "nonzero_without_fail"),
    ]
    bad_count = context(4)
    case_specs.append(("controller-count-mismatch", positive, bad_count, False, False, "completion_count"))
    bad_environment = context(3)
    bad_environment["invocation"]["environment"].pop("RUNTESTFLAGS")
    case_specs.append(("missing-explicit-environment", positive, bad_environment, False, False, "context_dejagnu_environment"))
    bad_target = context(3)
    bad_target["target"] = "aarch64-unknown-linux-gnu"
    case_specs.append(("embedded-target-mismatch", positive, bad_target, False, False, "target_context_mismatch"))
    outcomes = []
    for name, text, ctx, complete, strict, expected_issue in case_specs:
        path = fixtures / (name + ".sum")
        path.write_text(text)
        result = parse_dejagnu_sum(path, context=ctx)
        issue_codes = sorted({issue["code"] for issue in result["issues"]})
        if result["complete"] != complete or result["strict_eligible"] != strict:
            raise AssertionError((name, result["complete"], result["strict_eligible"], result["issues"]))
        if expected_issue and expected_issue not in issue_codes:
            raise AssertionError((name, expected_issue, issue_codes))
        if name == "source-positive":
            assert result["counts"] == {"PASS": 2, "XFAIL": 1}
            assert result["metrics"]["unique_test_identities"] == 2
        if name == "source-two-boards":
            assert result["counts"] == {"PASS": 2}
            assert len(result["summary_blocks"]) == 3
        outcomes.append({"fixture": path.relative_to(ROOT).as_posix(),
                         "fixture_sha256": digest(path), "complete": result["complete"],
                         "strict_eligible": result["strict_eligible"], "counts": result["counts"],
                         "issue_codes": issue_codes, "expected_behavior_matched": True})
    assert warning_trace["counts"]["UNRESOLVED"] == 1
    assert warning_trace["counts"]["PASS"] == 0
    # Exercise the upstream source-distributed AWK parser independently.
    awk_script = ROOT / "source/dejagnu-1.6.3/commands/report-card.awk"
    awk = subprocess.run(["awk", "-f", str(awk_script), "source-all-nine-statuses.sum"],
                         cwd=fixtures, text=True, capture_output=True, check=True)
    (ROOT / "evidence/upstream-report-card.txt").write_text(awk.stdout)
    assert "PASS" in awk.stdout and "FAIL" in awk.stdout
    # KPASS/XPASS and KFAIL/XFAIL are combined as ?PASS and ?FAIL by upstream.
    data_line = next(line for line in awk.stdout.splitlines() if line.startswith("source-all-nine-statuses  |"))
    numbers = [int(token) for token in data_line.split("|", 1)[1].split()]
    assert numbers == [1, 1, 2, 2, 1, 1, 1], numbers
    result = {
        "schema_version": 1, "status": "passed", "cases": outcomes,
        "case_count": len(outcomes), "scope": "source-generated format and conservative parser checks only",
        "cpg_parser_sha256": digest(args.cpg_root / "compiler_playground/upstream_results.py"),
        "source_traces": {"positive": positive_trace, "nine_statuses": mixed_trace,
                          "two_boards": board_trace, "warning_threshold": warning_trace,
                          "empty": empty_trace},
        "upstream_awk": {"script_sha256": digest(awk_script), "returncode": awk.returncode,
                         "combined_counts": numbers,
                         "stdout": "evidence/upstream-report-card.txt"},
        "gcc_regression_executed": False, "expect_harness_installed": False,
        "synthetic_controller_contexts_are_not_execution_receipts": True,
        "functional_qualification_increment": 0,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed", "case_count": len(outcomes),
                      "tcl": positive_trace["tcl_patchlevel"], "scope": result["scope"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
