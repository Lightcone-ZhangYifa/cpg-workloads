#!/usr/bin/env python3
"""Installed functional check for pytest; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pytest, work):
    """Run real passing, failing and empty suites in isolated child processes."""
    import os
    import sys
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    environment.pop("PYTEST_ADDOPTS", None)
    passing = work / "test_pass.py"
    passing.write_text("import pytest\n@pytest.mark.parametrize('x',[0,1,2])\ndef test_square(x):\n    assert x*x >= 0\n")
    base = [sys.executable, "-I", "-m", "pytest", "-q", "-c", "/dev/null", "--confcutdir", str(work)]
    result = child([*base, passing], cwd=work, environment=environment)
    require("3 passed" in result.stdout, "Passing tests were not actually collected")
    failing = work / "test_failure.py"
    failing.write_text("def test_expected_failure():\n    assert 1 == 2\n")
    result = child([*base, failing], expected=1, cwd=work, environment=environment)
    require("1 failed" in result.stdout, "Failing test was not reported")
    empty = work / "empty"
    empty.mkdir()
    child([*base, empty], expected=5, cwd=work, environment=environment)
    return {"checks": ["parametrized-test-execution", "failing-test-exit-1", "empty-suite-exit-5"], "external_plugins": "disabled for this check"}

if __name__ == "__main__":
    raise SystemExit(main('pytest', 'pytest', functional))
