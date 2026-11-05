"""Reproduce the measurement adapter tests and a small real scheduling demo.

Does not download, install, or invoke the five upstream resources. Format tests
use synthetic contracts, labeled here; the paired command demo runs Python.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    out = args.output.resolve()
    if out.exists():
        raise SystemExit("Use a fresh output directory; evidence is never overwritten.")
    out.mkdir(parents=True)
    sys.path.insert(0, str(root / "src"))
    from measurement_reuse import MeasurementError, run_pairs

    test_command = [sys.executable, "-O", str(root / "tests" / "test_measurement_reuse.py")]
    tests = subprocess.run(test_command, capture_output=True, text=True, timeout=45)
    (out / "tests.stdout.log").write_text(tests.stdout)
    (out / "tests.stderr.log").write_text(tests.stderr)
    if tests.returncode:
        raise SystemExit("Contract tests failed; see preserved logs.")
    count = re.search(r"Ran (\d+) tests", tests.stderr)
    if count is None or int(count[1]) < 39:
        raise SystemExit("Unexpected empty or incomplete test suite.")
    n = 120000
    expected = ((n - 1) * n * (2 * n - 1) // 6)
    oracle = hashlib.sha256(f"{expected}\n".encode()).hexdigest()
    workload = root / "examples" / "pair_workload.py"
    spec = {"baseline": [sys.executable, str(workload), "baseline", str(n)],
            "candidate": [sys.executable, str(workload), "candidate", str(n)],
            "blocks": 6, "seed": 3501, "warmups": 1, "timeout_seconds": 10,
            "expected_stdout_sha256": oracle,
            "workload_sha256": hashlib.sha256(workload.read_bytes()).hexdigest()}
    (out / "demo-spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    report = run_pairs(spec, out / "actual-paired-demo")
    wrong = {**spec, "candidate": [sys.executable, "-c", "print('incorrect')"]}
    try:
        run_pairs(wrong, out / "actual-wrong-output")
    except MeasurementError:
        pass
    else:
        raise SystemExit("Wrong output unexpectedly accepted.")
    timeout = {**spec, "baseline": [sys.executable, "-c", "import time;time.sleep(10)"],
               "timeout_seconds": .05}
    try:
        run_pairs(timeout, out / "actual-timeout")
    except MeasurementError:
        pass
    else:
        raise SystemExit("Timeout unexpectedly accepted.")
    background = {**spec, "baseline": [sys.executable, "-c",
        "import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print('background fixture')"]}
    background["expected_stdout_sha256"] = hashlib.sha256(b"background fixture\n").hexdigest()
    try:
        run_pairs(background, out / "actual-background-descendant")
    except MeasurementError:
        cleanup = json.loads((out / "actual-background-descendant" / "report.json").read_text())["invocations"][0]["cleanup"]
        if not cleanup["unexpected_descendants"] or not cleanup["confirmed"] or cleanup["process_group_present_after"] is not False:
            raise SystemExit("Background descendant was not rejected and cleaned as expected.")
    else:
        raise SystemExit("Background descendant unexpectedly accepted.")
    summary = {"status": "passed", "tests": int(count[1]), "python_optimized_mode": True,
               "actual_paired_blocks": len(report["pairs"]),
               "actual_timed_invocations": len([x for x in report["invocations"] if x["kind"] == "measurement"]),
               "actual_failed_output_rejected": True, "actual_timeout_rejected": True,
               "actual_background_descendant_rejected_and_cleaned": True,
               "upstream_tool_executions": 0, "upstream_tools_installed": 0,
               "formal_qualification_changes": 0,
               "scope": "adapter/integration checks only; no five-tool rerun or performance claim"}
    (out / "validation.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
