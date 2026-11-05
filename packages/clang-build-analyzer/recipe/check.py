#!/usr/bin/env python3
"""Check installed upstream fixtures and trace capture/analysis/error semantics."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

FIXTURES = ("blender-mac-clang14", "clang11-pid-45", "hlsl2glsl-mac-clang-10.0-dev",
            "libreoffice-skiahelper-clang-11-dev", "self-win-clang-13.0", "self-win-clang-16.0",
            "self-win-clang-19.1", "self-win-clang-cl-10.0rc2", "self-win-clang-cl-9.0rc2",
            "verylong-symbol-name-38")


def fixtures(root):
    names = tuple(sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")))
    if names != FIXTURES:
        raise RuntimeError("The exact ten pinned upstream fixture directories must be present")
    for name in names:
        path = root / name
        expected = path / "_AnalysisOutputExpected.txt"
        if not expected.is_file() or not expected.stat().st_size or not list(path.glob("*.json")):
            raise RuntimeError("Missing original oracle or trace input in fixture: " + name)
    return names


def analysis(text, count, frontend, backend):
    for pattern in (rf"Compilation \({count} times\):", rf"Parsing \(frontend\):\s+{re.escape(frontend)} s",
                    rf"Codegen & opts \(backend\):\s+{re.escape(backend)} s"):
        if re.search(pattern, text) is None:
            raise RuntimeError("Capture analysis differs from the synthetic trace oracle: " + pattern)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--case", choices=("upstream-tests", "trace-workflow"), required=True)
    args = parser.parse_args()
    parent = args.build or Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="clang-build-analyzer-" + args.case + "-", dir=parent))
    executable = args.prefix / "bin/ClangBuildAnalyzer"
    original = args.prefix / "share/clang-build-analyzer/source"
    report = {"schema_version": 1, "resource": "clang-build-analyzer", "case": args.case,
              "status": "running", "commands": [], "programs": [], "work": str(work),
              "scope": "Pinned upstream archived traces and explicit synthetic trace semantics; no new Clang compile, physical timing, LTO/linker analysis or official benchmark score."}
    environment = dict(os.environ)
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH"):
        environment.pop(name, None)

    def run(label, argv, *, negative=False):
        command = [str(x) for x in argv]
        done = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=120, env=environment)
        (work / (label + ".stdout")).write_text(done.stdout)
        (work / (label + ".stderr")).write_text(done.stderr)
        report["commands"].append({"label": label, "argv": command, "returncode": done.returncode,
                                   "expected_nonzero": negative, "stdout": label + ".stdout", "stderr": label + ".stderr"})
        if done.returncode < 0 or (done.returncode == 0) == negative:
            raise RuntimeError("Unexpected exit status: " + label)
        return done.stdout

    try:
        if args.case == "upstream-tests":
            names = fixtures(original / "tests")
            target = work / "tests"
            shutil.copytree(original / "tests", target)
            shutil.copy2(original / "ClangBuildAnalyzer.ini", work / "ClangBuildAnalyzer.ini")
            expected = {name: hashlib.sha256((target / name / "_AnalysisOutputExpected.txt").read_bytes()).hexdigest() for name in names}
            # Original expected output includes the relative tests/ path.
            # Run the upstream command from its copied fixture root unchanged.
            text = run("official-tests", [executable, "--test", "tests"])
            if len(re.findall(r"Running test '", text)) != len(names):
                raise RuntimeError("Upstream CLI did not actually run all ten fixtures")
            for name in names:
                oracle = target / name / "_AnalysisOutputExpected.txt"
                actual = target / name / "_AnalysisOutput.txt"
                if hashlib.sha256(oracle.read_bytes()).hexdigest() != expected[name] or actual.read_bytes().replace(b"\r\n", b"\n") != oracle.read_bytes().replace(b"\r\n", b"\n"):
                    raise RuntimeError("Original upstream output oracle changed or was not met: " + name)
            report["upstream_fixtures"] = [{"name": name, "expected_sha256": expected[name]} for name in names]
        else:
            traces = work / "traces"
            traces.mkdir()
            def trace():
                events = []
                for name, start, duration, detail in (("Source", 10000, 20000, "cpg-header.h"),
                        ("InstantiateFunction", 50000, 30000, "cpg_template<int>"),
                        ("Frontend", 0, 500000, ""), ("Backend", 500000, 300000, ""),
                        ("ExecuteCompiler", 0, 800000, "")):
                    event = {"pid": 100, "tid": 5, "ph": "X", "name": name, "ts": start, "dur": duration}
                    if detail:
                        event["args"] = {"detail": detail}
                    events.append(event)
                return {"traceEvents": events}
            old = traces / "old.json"
            old.write_text(json.dumps(trace()))
            os.utime(old, (1, 1))
            run("start", [executable, "--start", traces])
            session = traces / "ClangBuildAnalyzerSession.txt"
            if not session.is_file() or not session.stat().st_size:
                raise RuntimeError("Start did not create a session record")
            nested = traces / "nested"
            nested.mkdir()
            (nested / "fresh.json").write_text(json.dumps(trace()))
            run("stop", [executable, "--stop", traces, work / "session.bin"])
            analysis(run("analyze-session", [executable, "--analyze", work / "session.bin"]), 1, "0.5", "0.3")
            run("all", [executable, "--all", traces, work / "all.bin"])
            analysis(run("analyze-all", [executable, "--analyze", work / "all.bin"]), 2, "1.0", "0.6")
            empty = work / "empty"
            empty.mkdir()
            run("empty-input", [executable, "--all", empty, work / "empty.bin"], negative=True)
            run("missing-session", [executable, "--stop", empty, work / "missing-session.bin"], negative=True)
            run("missing-capture", [executable, "--analyze", work / "missing.bin"], negative=True)
            bad = work / "bad"
            bad.mkdir()
            (bad / "broken.json").write_text('{"traceEvents": [ invalid')
            run("malformed-json", [executable, "--all", bad, work / "broken.bin"], negative=True)
            run("unknown-option", [executable, "--cpg-invalid-option"], negative=True)
            (work / "invalid.bin").write_bytes(b"not a ClangBuildAnalyzer capture")
            run("invalid-capture", [executable, "--analyze", work / "invalid.bin"], negative=True)
            report["synthetic_oracle"] = {"session_compilations": 1, "all_compilations": 2,
                                           "session_frontend_seconds": 0.5, "session_backend_seconds": 0.3,
                                           "elapsed_performance_measurement": False}
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        (work / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
