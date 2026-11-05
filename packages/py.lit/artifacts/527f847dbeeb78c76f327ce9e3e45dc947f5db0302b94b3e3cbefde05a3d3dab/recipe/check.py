#!/usr/bin/env python3
"""Installed LLVM lit check using an actual four-result shell-test suite."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, main, require

def functional(lit, work):
    """Execute PASS/FAIL/XFAIL/UNSUPPORTED cases and inspect recorded result codes."""
    suite = work / "suite"; suite.mkdir()
    (suite / "lit.cfg.py").write_text(
        "import os, sys, lit.formats\n"
        "config.name='CPG-qualification'\n"
        "config.test_format=lit.formats.ShTest(execute_external=False)\n"
        "config.suffixes=['.test']\n"
        "config.test_source_root=os.path.dirname(__file__)\n"
        "config.test_exec_root=config.test_source_root\n"
        "config.substitutions.append(('%python', sys.executable))\n")
    fixtures = {
        "pass.test": '# RUN: %python -c "import sys; print(42); sys.exit(0)"\n',
        "fail.test": '# RUN: %python -c "import sys; sys.exit(3)"\n',
        "xfail.test": '# XFAIL: *\n# RUN: %python -c "import sys; sys.exit(3)"\n',
        "unsupported.test": '# UNSUPPORTED: *\n# RUN: %python -c "raise RuntimeError(\'must not execute\')"\n',
    }
    for name, source in fixtures.items(): (suite / name).write_text(source)
    launcher = work / "run_lit.py"; launcher.write_text("from lit.main import main\nmain()\n")
    report = work / "all-results.json"
    result = child([sys.executable, "-I", launcher, "-j", "1", "-v", "-o", report, suite], expected=1)
    rows = json.loads(report.read_text())["tests"]
    observed = {Path(row["name"].split(" :: ")[-1]).name: row["code"] for row in rows}
    require(observed == {"pass.test": "PASS", "fail.test": "FAIL", "xfail.test": "XFAIL", "unsupported.test": "UNSUPPORTED"},
            f"Wrong or incomplete lit execution results: {observed}")
    fail = next(row for row in rows if row["code"] == "FAIL")
    require(bool(fail.get("output")) and "3" in fail["output"], "Failing subprocess diagnostics missing")
    filtered_report = work / "filtered-results.json"
    child([sys.executable, "-I", launcher, "-j", "1", "--filter", "(pass|xfail|unsupported)\\.test$",
           "-o", filtered_report, suite])
    filtered = json.loads(filtered_report.read_text())["tests"]
    require(sorted(row["code"] for row in filtered) == ["PASS", "UNSUPPORTED", "XFAIL"], "Filtered execution did not preserve expected outcomes")
    child([sys.executable, "-I", launcher, "--not-a-real-lit-option"], expected=2)
    return {"checks": ["real-shell-test-execution", "complete-result-inventory", "pass-fail-xfail-unsupported",
                       "failing-command-diagnostic", "suite-failure-exit-code", "filtered-success-exit-code", "invalid-option"],
            "test_results": observed, "suite_cases": len(rows)}

if __name__ == "__main__":
    raise SystemExit(main("lit", "lit", functional))
