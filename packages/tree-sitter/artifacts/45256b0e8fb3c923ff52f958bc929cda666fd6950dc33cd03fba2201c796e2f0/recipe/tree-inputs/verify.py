#!/usr/bin/env python3
"""Offline bounded functionality and unchanged upstream corpus verification."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

# Package checks must not create __pycache__ inside an installed payload.
sys.dont_write_bytecode = True
from api import Parser, point_at

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_ranges(snapshot: dict, source: bytes) -> None:
    assert snapshot["source_bytes"] == len(source)
    for index, node in enumerate(snapshot["nodes"]):
        assert node["index"] == index, node
        start, end = node["start_byte"], node["end_byte"]
        assert 0 <= start <= end <= len(source), node
        assert node["start_point"] == list((point_at(source, start).row, point_at(source, start).column)), node
        assert node["end_point"] == list((point_at(source, end).row, point_at(source, end).column)), node
        if node["parent"] is not None:
            assert 0 <= node["parent"] < index, node
            parent = snapshot["nodes"][node["parent"]]
            assert parent["start_byte"] <= start <= end <= parent["end_byte"], node


def runtime_tests(runtime_prefix: Path, grammars_prefix: Path, evidence: Path) -> dict:
    programs = {
        "c": "// 非ASCII: π\nint add(int x) { return x + 1; }\n",
        "cpp": "// 非ASCII: π\nnamespace ns { int add(int x) { return x + 1; } }\n",
        "rust": "// 非ASCII: π\nfn add(x: i32) -> i32 { x + 1 }\n",
    }
    cases = []
    snapshots = {}
    for lang, program in programs.items():
        snapshots[lang] = []
        with Parser(lang, runtime_prefix=runtime_prefix, grammars_prefix=grammars_prefix) as parser:
            def check(name: str, snapshot: dict, expect_error: bool = False, compare_fresh: bool = True) -> None:
                check_ranges(snapshot, parser.source)
                assert snapshot["has_error"] is expect_error, (lang, name, snapshot)
                if compare_fresh:
                    with Parser(lang, runtime_prefix=runtime_prefix, grammars_prefix=grammars_prefix) as fresh:
                        expected = fresh.parse(parser.source)
                    assert snapshot == expected, (lang, name, "incremental differs from full reparse")
                cases.append({"language": lang, "name": name, "status": "passed", "bytes": len(parser.source), "nodes": len(snapshot["nodes"]), "has_error": snapshot["has_error"], "full_reparse_equal": compare_fresh})
                snapshots[lang].append({"name": name, "source_utf8": parser.source.decode(), "snapshot": snapshot})

            check("valid_program", parser.parse(program))
            add_start = parser.source.index(b"add")
            add_nodes = [n for n in parser.snapshot()["nodes"] if n["type"] == "identifier" and n["start_byte"] == add_start and n["end_byte"] == add_start + 3]
            assert len(add_nodes) == 1
            cases.append({"language": lang, "name": "identifier_exact_byte_range", "status": "passed", "start_byte": add_start, "end_byte": add_start + 3, "start_point": add_nodes[0]["start_point"]})
            literal = parser.source.rindex(b"1")
            check("length_changing_literal_edit", parser.edit(literal, literal + 1, "1234"))
            pi_start = parser.source.index("π".encode())
            check("multibyte_utf8_edit", parser.edit(pi_start, pi_start + len("π".encode()), "中文🙂"))
            inserted = "/* 插入\n第二行 */\n".encode()
            check("multiline_prefix_insertion", parser.edit(0, 0, inserted))
            check("multiline_prefix_deletion", parser.edit(0, len(inserted), b""))
            operand = parser.source.rindex(b"1234")
            check("incomplete_expression_error", parser.edit(operand, operand + 4, b""), expect_error=True)
            check("syntax_error_recovery", parser.edit(operand, operand, b"1234"))
            # A byte offset inside a multibyte code point must be rejected before
            # the native edit, then the previously valid tree remains usable.
            middle = parser.source.index("中".encode()) + 1
            before = parser.snapshot()
            try:
                parser.edit(middle, middle, "x")
            except UnicodeDecodeError:
                pass
            else:
                raise AssertionError("edit in the middle of UTF-8 was accepted")
            assert parser.snapshot() == before
            cases.append({"language": lang, "name": "utf8_boundary_rejected_without_tree_mutation", "status": "passed"})
            if lang == "c":
                # Regression: native parsing succeeds for deep valid input, but
                # the former recursive Python snapshot raised RecursionError.
                depth = 1500
                deep_source = "int deep(void) { return " + "(" * depth + "1" + ")" * depth + "; }\n"
                check("deep_parentheses_snapshot", parser.parse(deep_source))
                cases[-1].update({"parenthesis_depth": depth, "python_recursion_limit": sys.getrecursionlimit()})
                literal = parser.source.index(b"1")
                check("deep_parentheses_incremental_edit", parser.edit(literal, literal + 1, b"12345"))
                cases[-1].update({"parenthesis_depth": depth, "python_recursion_limit": sys.getrecursionlimit()})
    (evidence / "runtime-snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n")
    result = {"status": "passed", "passed": len(cases), "failed": 0, "skipped": 0, "cases": cases,
              "scope": "C/C++/Rust syntax parsing, incremental edits versus full reparse, every node byte/point range, malformed syntax detection and repair, and 1500-level C expression snapshot/edit regression. No semantic/type/name-resolution claim."}
    (evidence / "runtime-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def parse_outcomes(node: dict | list) -> list[str]:
    if isinstance(node, list):
        return [outcome for child in node for outcome in parse_outcomes(child)]
    if "outcome" in node:
        outcome = node["outcome"]
        return [outcome if isinstance(outcome, str) else next(iter(outcome))]
    return parse_outcomes(node.get("children", []))


def summarize_parse_counts(counts: dict[str, int]) -> dict[str, int]:
    # CLI 0.26.10 TestOutcome::Platform means the fixture does not apply on
    # this platform. Updated means expected output was changed, never passed.
    skipped_outcomes = {"Skipped", "Platform"}
    return {
        "passed": counts.get("Passed", 0),
        "skipped": sum(value for key, value in counts.items() if key in skipped_outcomes),
        "failed": sum(value for key, value in counts.items() if key != "Passed" and key not in skipped_outcomes),
    }


def corpus_tests(runtime_prefix: Path, grammars_prefix: Path, source_dir: Path, work: Path, evidence: Path) -> dict:
    cli = runtime_prefix / "bin/tree-sitter"
    env = os.environ.copy()
    env.update({"XDG_CACHE_HOME": str(work / "cache"), "XDG_CONFIG_HOME": str(work / "config"), "NO_COLOR": "1"})
    results = []
    manifests = []
    for lang in ("c", "cpp", "rust"):
        original = source_dir / ("tree-sitter-" + lang)
        directory = work / ("upstream-" + lang)
        if directory.exists():
            shutil.rmtree(directory)
        shutil.copytree(original, directory)
        if lang == "cpp":
            # The exact 0.23.1 input is pinned by the upstream C++ package-lock.
            # Do not run npm install or execute its lifecycle scripts.
            shutil.copytree(source_dir / "tree-sitter-c-cpp-base", directory / "node_modules/tree-sitter-c")
        before = [{"path": str(p.relative_to(directory)), "sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted((directory / "test/corpus").rglob("*")) if p.is_file()]
        assert before, "upstream corpus not found for " + lang
        command = [str(cli), "test", "--json-summary", "--lib-path", str(grammars_prefix / ("lib/libtree-sitter-" + lang + ".so")), "--lang-name", lang]
        start = time.monotonic()
        completed = subprocess.run(command, cwd=directory, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (evidence / (lang + "-corpus.stdout.json")).write_text(completed.stdout)
        (evidence / (lang + "-corpus.stderr.log")).write_text(completed.stderr)
        summary = json.loads(completed.stdout)
        counts = dict(collections.Counter(parse_outcomes(summary["parse_results"])))
        classified = summarize_parse_counts(counts)
        passed, skipped, failed = classified["passed"], classified["skipped"], classified["failed"]
        after = [{"path": str(p.relative_to(directory)), "sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted((directory / "test/corpus").rglob("*")) if p.is_file()]
        unchanged = before == after
        assert unchanged, "corpus expected outputs were mutated"
        assert completed.returncode == 0 and failed == 0 and passed > 0, (lang, completed.returncode, counts, completed.stderr)
        result = {"language": lang, "status": "passed", "argv": command, "cwd": str(directory), "returncode": completed.returncode,
                  "seconds": time.monotonic() - start, "outcomes": counts, "passed": passed, "failed": failed, "skipped": skipped,
                  "corpus_files": len(before), "corpus_unchanged": unchanged, "parse_stats": summary.get("parse_stats"),
                  "additional_upstream_tests": {key: summary.get(key, []) for key in ("highlight_results", "tag_results", "query_results")}}
        manifests.append({"language": lang, "source_directory": str(original), "files": before})
        results.append(result)
    (evidence / "upstream-corpus-files.json").write_text(json.dumps(manifests, indent=2) + "\n")
    result = {"status": "passed", "passed": sum(x["passed"] for x in results), "failed": sum(x["failed"] for x in results), "skipped": sum(x["skipped"] for x in results), "languages": results,
              "scope": "Official unchanged test/corpus from exactly three locked grammar repositories, run by the official matching CLI with compiled upstream parsers. Additional query/highlight/tag tests are recorded separately."}
    (evidence / "corpus-result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    if not __debug__:
        raise RuntimeError("Verification requires assertions; do not use python -O or PYTHONOPTIMIZE")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("runtime", "corpus", "all"), default="all")
    parser.add_argument("--runtime-prefix", type=Path, default=ROOT / "install")
    parser.add_argument("--grammars-prefix", type=Path, default=ROOT / "install")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "sources")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/verify")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "evidence")
    args = parser.parse_args()
    args.work_dir = args.work_dir.resolve()
    args.evidence_dir = args.evidence_dir.resolve()
    readonly_roots = {"source-dir": args.source_dir.resolve(), "runtime-prefix": args.runtime_prefix.resolve(), "grammars-prefix": args.grammars_prefix.resolve()}
    for writable_name, writable in (("work-dir", args.work_dir), ("evidence-dir", args.evidence_dir)):
        for readonly_name, readonly in readonly_roots.items():
            if writable.is_relative_to(readonly) or readonly.is_relative_to(writable):
                raise ValueError(f"{writable_name} must not overlap read-only {readonly_name}: {writable} / {readonly}")
    # corpus_tests refreshes only these disposable directories. Evidence must
    # not be placed there, even when evidence is otherwise nested under work.
    for language in ("c", "cpp", "rust"):
        disposable = args.work_dir / ("upstream-" + language)
        if args.evidence_dir.is_relative_to(disposable):
            raise ValueError("evidence-dir must not be inside disposable upstream corpus work")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    result = {"status": "passed", "network_required": False, "scope": args.scope}
    if args.scope in ("runtime", "all"):
        result["runtime"] = runtime_tests(args.runtime_prefix.resolve(), args.grammars_prefix.resolve(), args.evidence_dir)
    if args.scope in ("corpus", "all"):
        result["corpus"] = corpus_tests(args.runtime_prefix.resolve(), args.grammars_prefix.resolve(), args.source_dir.resolve(), args.work_dir, args.evidence_dir)
    (args.evidence_dir / "verification-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed", "scope": args.scope, "runtime_passed": result.get("runtime", {}).get("passed"), "upstream_corpus_passed": result.get("corpus", {}).get("passed")}))


if __name__ == "__main__":
    main()
