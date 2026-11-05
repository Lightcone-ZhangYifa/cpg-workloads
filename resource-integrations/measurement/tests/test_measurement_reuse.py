"""Synthetic format contracts and actual runner failures, not upstream tool runs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from measurement_reuse import (MeasurementError, load_json, normalize, paired_plan, _kill_group,
    parse_asv, parse_gnu_time, parse_google_benchmark, parse_hyperfine,
    parse_pyperf, run_pairs)


class FormatContracts(unittest.TestCase):
    def google(self):
        return {"context": {"json_schema_version": 1}, "benchmarks": [
            {"name": "sum", "run_name": "sum", "run_type": "iteration", "iterations": 100,
             "real_time": 10, "cpu_time": 9, "time_unit": "ns"},
            {"name": "sum_mean", "run_name": "sum", "run_type": "aggregate",
             "real_time": 999, "cpu_time": 999, "time_unit": "ns"}]}

    def pyperf(self):
        return {"version": "1.0", "metadata": {"name": "sum", "loops": 100, "unit": "second"},
                "benchmarks": [{"runs": [
                    {"metadata": {"calibrate_loops": 100}, "warmups": [[1, .3]], "values": [.8]},
                    {"warmups": [[100, .2]], "values": [.1, .12]}]}]}

    def asv(self):
        doc = {"version": 2, "commit_hash": "fixture-commit", "env_name": "existing",
               "result_columns": ["result", "params", "version", "samples", "profile"],
               "results": {"time_sum": [[.1, .2], [["32", "1024"]], "v1", [[.1, .11], [.2, .22]]]}}
        catalog = {"time_sum": {"type": "time", "unit": "seconds", "version": "v1", "params": [["32", "1024"]]}}
        return doc, catalog

    def hyperfine(self):
        return {"results": [{"command": "fixture", "times": [.1, .2], "exit_codes": [0, 0], "mean": 500}]}

    def test_google_ignores_aggregates_converts_units(self):
        records = parse_google_benchmark(self.google())
        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(records[0]["samples"][0], 1e-8)
        self.assertEqual(records[0]["raw_indices"], [0])

    def test_google_rejects_aggregate_only(self):
        doc = self.google(); doc["benchmarks"].pop(0)
        with self.assertRaises(MeasurementError): parse_google_benchmark(doc)

    def test_google_rejects_skipped(self):
        doc = self.google(); doc["benchmarks"][0]["error_occurred"] = True
        with self.assertRaises(MeasurementError): parse_google_benchmark(doc)

    def test_google_rejects_unknown_unit(self):
        doc = self.google(); doc["benchmarks"][0]["time_unit"] = "cycles"
        with self.assertRaises(MeasurementError): parse_google_benchmark(doc)

    def test_google_rejects_zero_iterations(self):
        doc = self.google(); doc["benchmarks"][0]["iterations"] = 0
        with self.assertRaises(MeasurementError): parse_google_benchmark(doc)

    def test_google_rejects_bool_as_iteration_count(self):
        doc = self.google(); doc["benchmarks"][0]["iterations"] = True
        with self.assertRaises(MeasurementError): parse_google_benchmark(doc)

    def test_google_rejects_bool_or_float_schema(self):
        for value in (True, 1.0):
            doc = self.google(); doc["context"]["json_schema_version"] = value
            with self.subTest(value=value), self.assertRaises(MeasurementError): parse_google_benchmark(doc)

    def test_pyperf_excludes_calibration_and_warmups_no_second_division(self):
        record = parse_pyperf(self.pyperf())[0]
        self.assertEqual(record["samples"], [.1, .12])
        self.assertEqual(record["raw_indices"], [[1, 0], [1, 1]])
        self.assertTrue(record["context"]["runs"][0]["calibration"])

    def test_pyperf_accepts_zero_warmup_without_counting_it(self):
        doc = self.pyperf()
        doc["benchmarks"][0]["runs"][1]["warmups"] = [[100, 0.0]]
        record = parse_pyperf(doc)[0]
        self.assertEqual(record["samples"], [.1, .12])
        self.assertEqual(record["context"]["runs"][1]["warmups"], [[100, 0.0]])

    def test_pyperf_rejects_zero_measured_value(self):
        doc = self.pyperf()
        doc["benchmarks"][0]["runs"][1]["values"] = [0.0]
        with self.assertRaises(MeasurementError):
            parse_pyperf(doc)

    def test_pyperf_rejects_non_time(self):
        doc = self.pyperf(); doc["metadata"]["unit"] = "byte"
        with self.assertRaises(MeasurementError): parse_pyperf(doc)

    def test_pyperf_rejects_calibration_only(self):
        doc = self.pyperf(); doc["benchmarks"][0]["runs"].pop()
        with self.assertRaises(MeasurementError): parse_pyperf(doc)

    def test_pyperf_rejects_zero_loops(self):
        doc = self.pyperf(); doc["metadata"]["loops"] = 0
        with self.assertRaises(MeasurementError): parse_pyperf(doc)

    def test_pyperf_rejects_nonfinite(self):
        doc = self.pyperf(); doc["benchmarks"][0]["runs"][1]["values"] = [float("nan")]
        with self.assertRaises(MeasurementError): parse_pyperf(doc)

    def test_pyperf_rejects_unknown_schema(self):
        doc = self.pyperf(); doc["version"] = "2.0"
        with self.assertRaises(MeasurementError): parse_pyperf(doc)

    def test_asv_preserves_parameter_grid_and_accepts_trimmed_tail(self):
        records = parse_asv(*self.asv())
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["context"]["parameters"], ["1024"])
        self.assertEqual(records[1]["samples"], [.2, .22])

    def test_asv_rejects_changed_benchmark_version(self):
        doc, catalog = self.asv(); catalog["time_sum"]["version"] = "v2"
        with self.assertRaises(MeasurementError): parse_asv(doc, catalog)

    def test_asv_rejects_changed_parameter_order(self):
        doc, catalog = self.asv(); catalog["time_sum"]["params"][0].reverse()
        with self.assertRaises(MeasurementError): parse_asv(doc, catalog)

    def test_asv_rejects_failed_result(self):
        doc, catalog = self.asv(); doc["results"]["time_sum"][0][0] = None
        with self.assertRaises(MeasurementError): parse_asv(doc, catalog)

    def test_asv_rejects_summary_only(self):
        doc, catalog = self.asv(); doc["results"]["time_sum"].pop()
        with self.assertRaises(MeasurementError): parse_asv(doc, catalog)

    def test_asv_rejects_duplicate_column(self):
        doc, catalog = self.asv(); doc["result_columns"].append("samples")
        with self.assertRaises(MeasurementError): parse_asv(doc, catalog)

    def test_asv_rejects_track_count_as_time(self):
        doc, catalog = self.asv(); catalog["time_sum"].update(type="track", unit="unit")
        with self.assertRaises(MeasurementError): parse_asv(doc, catalog)

    def test_asv_rejects_float_schema(self):
        doc, catalog = self.asv(); doc["version"] = 2.0
        with self.assertRaises(MeasurementError): parse_asv(doc, catalog)

    def test_normalize_uses_same_bytes_for_parsing_and_both_digests(self):
        doc, catalog = self.asv()
        source, catalog_path = Path("/virtual/result.json"), Path("/virtual/benchmarks.json")
        raw = {source: json.dumps(doc).encode(), catalog_path: json.dumps(catalog).encode()}
        calls = []
        def read_once(path):
            if path in calls:
                raise RuntimeError("source read twice: identity could race content")
            calls.append(path)
            return raw[path]
        with mock.patch.object(Path, "read_bytes", read_once):
            result = normalize("py.asv", source, catalog=catalog_path)
        self.assertEqual(result["source_sha256"], hashlib.sha256(raw[source]).hexdigest())
        self.assertEqual(result["catalog"]["sha256"], hashlib.sha256(raw[catalog_path]).hexdigest())
        self.assertEqual(calls, [source, catalog_path])

    def test_hyperfine_reads_samples_not_summary(self):
        self.assertEqual(parse_hyperfine(self.hyperfine())[0]["samples"], [.1, .2])

    def test_hyperfine_rejects_ignored_error(self):
        doc = self.hyperfine(); doc["results"][0]["exit_codes"][0] = 1
        with self.assertRaises(MeasurementError): parse_hyperfine(doc)

    def test_hyperfine_rejects_missing_exit(self):
        doc = self.hyperfine(); doc["results"][0]["exit_codes"].pop()
        with self.assertRaises(MeasurementError): parse_hyperfine(doc)

    def test_hyperfine_rejects_zero_shell_corrected_time(self):
        doc = self.hyperfine(); doc["results"][0]["times"][0] = 0
        with self.assertRaises(MeasurementError): parse_hyperfine(doc)

    def test_time_retains_zero_as_resolution_limit(self):
        row = parse_gnu_time("CPG_TIME_V1\t0.00\t0.00\t0.00\t100\t0\n")[0]
        self.assertTrue(row["context"]["below_report_resolution"])

    def test_time_rejects_failure(self):
        with self.assertRaises(MeasurementError): parse_gnu_time("CPG_TIME_V1\t1\t0\t0\t100\t1\n")

    def test_time_rejects_concatenated_records(self):
        with self.assertRaises(MeasurementError): parse_gnu_time("CPG_TIME_V1\t1\t0\t0\t100\t0\n" * 2)

    def test_time_rejects_bad_locale(self):
        with self.assertRaises(MeasurementError): parse_gnu_time("CPG_TIME_V1\t0,15\t0\t0\t100\t0\n")

    def test_json_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"; p.write_text('{"x":1,"x":2}')
            with self.assertRaises(MeasurementError): load_json(p)


class PairedRunnerContracts(unittest.TestCase):
    def spec(self):
        return {"baseline": [sys.executable, "-c", "print(42)"],
                "candidate": [sys.executable, "-c", "print(42)"],
                "blocks": 2, "seed": 35, "warmups": 0, "timeout_seconds": 3,
                "expected_stdout_sha256": hashlib.sha256(b"42\n").hexdigest()}

    def test_order_balanced_and_reproducible(self):
        plan = paired_plan(8, 35)
        self.assertEqual(plan, paired_plan(8, 35))
        self.assertEqual(sum(x[0] == "baseline" for x in plan), 4)

    def test_reject_odd_blocks(self):
        with self.assertRaises(MeasurementError): paired_plan(3, 35)

    def test_actual_pair_and_correctness(self):
        with tempfile.TemporaryDirectory() as d:
            report = run_pairs(self.spec(), Path(d) / "out")
            self.assertTrue(report["accepted"])
            self.assertEqual(len(report["pairs"]), 2)
            self.assertTrue(all(x["correct"] for x in report["invocations"]))

    def test_actual_wrong_output_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            spec = self.spec(); spec["candidate"] = [sys.executable, "-c", "print(43)"]
            out = Path(d) / "out"
            with self.assertRaises(MeasurementError): run_pairs(spec, out)
            report = json.loads((out / "report.json").read_text())
            self.assertFalse(report["accepted"])
            self.assertFalse(report["invocations"][-1]["correct"])
            self.assertTrue((out / "raw-invocations.jsonl").is_file())

    def test_actual_timeout_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            spec = self.spec(); spec.update(timeout_seconds=.05)
            spec["baseline"] = [sys.executable, "-c", "import time;time.sleep(10)"]
            out = Path(d) / "out"
            with self.assertRaises(MeasurementError): run_pairs(spec, out)
            report = json.loads((out / "report.json").read_text())
            self.assertTrue(report["invocations"][0]["timeout"])

    def test_actual_background_descendant_rejected_and_cleaned(self):
        with tempfile.TemporaryDirectory() as d:
            spec = self.spec()
            code = ("import subprocess,sys;"
                    "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
                    "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print(42)")
            spec["baseline"] = [sys.executable, "-c", code]
            out = Path(d) / "out"
            with self.assertRaises(MeasurementError): run_pairs(spec, out)
            cleanup = json.loads((out / "report.json").read_text())["invocations"][0]["cleanup"]
            self.assertTrue(cleanup["unexpected_descendants"])
            self.assertTrue(cleanup["confirmed"])
            self.assertIs(cleanup["process_group_present_after"], False)

    def test_kill_group_completion_race_is_harmless(self):
        with mock.patch("os.killpg", side_effect=ProcessLookupError):
            self.assertIsNone(_kill_group(99999999))

    @unittest.skipUnless(os.name == "posix", "owned process-group cleanup requires POSIX")
    def test_actual_interrupt_preserves_evidence_and_cleans_only_owned_group(self):
        def exit_handler(signum, frame):
            raise SystemExit(23)

        cases = ((KeyboardInterrupt, signal.SIGINT, signal.default_int_handler),
                 (SystemExit, signal.SIGUSR1, exit_handler))
        for expected_error, signum, handler in cases:
            with self.subTest(interruption=expected_error.__name__), tempfile.TemporaryDirectory() as d:
                ready = Path(d) / "descendant-ready"
                cancelled, delivered = threading.Event(), threading.Event()
                spec = self.spec()
                spec["baseline"] = [sys.executable, "-c",
                    "import pathlib,subprocess,sys,time;"
                    "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                    f"pathlib.Path({str(ready)!r}).write_text('ready');time.sleep(30)"]
                sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

                def interrupt_after_descendant_started():
                    deadline = time.monotonic() + 2
                    while not cancelled.wait(.005) and time.monotonic() < deadline:
                        if ready.exists():
                            delivered.set()
                            os.kill(os.getpid(), signum)
                            return

                original_handler = signal.signal(signum, handler)
                sender = threading.Thread(target=interrupt_after_descendant_started)
                out = Path(d) / "out"
                try:
                    sender.start()
                    with self.assertRaises(expected_error) as caught:
                        run_pairs(spec, out)
                    if expected_error is SystemExit:
                        self.assertEqual(caught.exception.code, 23)
                    self.assertTrue(delivered.is_set())
                    report = json.loads((out / "report.json").read_text())
                    row = report["invocations"][0]
                    self.assertFalse(report["accepted"])
                    self.assertEqual(report["interrupted"], expected_error.__name__)
                    self.assertEqual(row["interrupted"], expected_error.__name__)
                    self.assertFalse(row["correct"])
                    self.assertTrue(row["cleanup"]["confirmed"])
                    self.assertIs(row["cleanup"]["process_group_present_after"], False)
                    with self.assertRaises(ProcessLookupError):
                        os.killpg(row["cleanup"]["owned_pgid"], 0)
                    raw = [json.loads(line) for line in (out / "raw-invocations.jsonl").read_text().splitlines()]
                    self.assertEqual(raw, report["invocations"])
                    self.assertIsNone(sentinel.poll(), "cleanup killed an unrelated process")
                finally:
                    cancelled.set()
                    sender.join(timeout=3)
                    signal.signal(signum, original_handler)
                    sentinel.kill()
                    sentinel.wait(timeout=3)

    def test_reject_existing_output(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(MeasurementError): run_pairs(self.spec(), Path(d))


if __name__ == "__main__":
    unittest.main(verbosity=2)
