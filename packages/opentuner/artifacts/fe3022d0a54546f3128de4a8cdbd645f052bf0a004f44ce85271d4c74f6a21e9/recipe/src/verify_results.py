"""Independently audit persisted C measurements and the eight task reports."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path


def strict_load(text):
    def invalid(value):
        raise ValueError("Non-standard JSON numeric value: " + value)
    return json.loads(text, parse_constant=invalid)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--ray-directory", default="ray-final")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.evidence).resolve()
    oracle = strict_load((root / "oracles.json").read_text())
    require(not (set(oracle["train_instances"]) & set(oracle["heldout_instances"])),
            "Training and held-out instance identifiers overlap")
    negative = strict_load((root / "negative-controls.json").read_text())
    require(set(negative) == {"wrong", "compile", "timeout", "constraint", "fractional"},
            "Missing negative-control category")
    require(all(x["rejected"] for x in negative.values()), "A negative control was accepted")
    directories = {
        "hypermapper": "hypermapper", "irace": "irace", "nevergrad": "nevergrad",
        "opentuner": "opentuner", "optuna": "optuna", "smac": "smac",
        "ytopt": "ytopt-complete", "ray-tune": args.ray_directory,
    }
    results = {}
    for tool, directory in directories.items():
        result_path = root / directory / "result.json"
        report = strict_load(result_path.read_text())
        require(report["status"] == "passed", tool + " report is not passed")
        rows = []
        evidence_files = sorted((root / directory).rglob("evaluations.jsonl"))
        require(evidence_files, tool + " has no persisted raw measurements")
        for path in evidence_files:
            rows.extend(strict_load(line) for line in path.read_text().splitlines() if line.strip())
        ids = [row["evaluation_id"] for row in rows]
        require(len(ids) == len(set(ids)), tool + " contains duplicated measurements")
        phase_counts = collections.Counter()
        for row in rows:
            instance = row["instance"]
            require(instance in oracle["instances"], tool + " contains an unknown instance")
            phase_counts[row["phase"]] += 1
            if row["phase"] == "heldout_replay":
                require(instance in oracle["heldout_instances"], tool + " replay used training data")
            else:
                require(instance in oracle["train_instances"], tool + " search used held-out data")
            value = row["objective_seconds"]
            if not row["valid_speed"]:
                require(value is None and row["status"] != "ok", tool + " counted failure as speed")
                continue
            require(row["status"] == "ok" and isinstance(value, (int, float))
                    and math.isfinite(value) and value > 0, tool + " has invalid runtime")
            require(row["compiler_returncode"] == 0 and row["binary_sha256"],
                    tool + " lacks successful real compilation")
            raw = row["raw_runs"]
            require(len(raw) >= 2 and raw[0]["warmup"], tool + " lacks a warmup and measured run")
            expected = oracle["instances"][instance]["checksum"]
            require(row["checksum"] == expected, tool + " checksum record disagrees with oracle")
            for run in raw:
                fields = run["stdout"].strip().split()
                require(run["returncode"] == 0 and len(fields) == 2
                        and int(fields[0]) > 0 and int(fields[1]) == expected,
                        tool + " retained an incorrect raw executable result")
        require(phase_counts["heldout_replay"] >= 3, tool + " lacks three held-out measurements")
        if tool == "irace":
            require(report["actual_training_evaluations"] == phase_counts["search"] <= 128,
                    "irace budget differs from actual evaluations")
            require(report["elite_count"] * 3 == phase_counts["heldout_replay"],
                    "Not every irace elite was independently replayed")
        if tool == "nevergrad":
            require(report["num_ask"] == report["num_tell"] == report["budget"] == 16,
                    "Nevergrad ask/tell budget mismatch")
        if tool == "optuna":
            require(report["restored_prior_trials"] == 9 and report["completed"] == 12
                    and report["failed_without_speed"] == 3 and report["total_trials"] == 15,
                    "Optuna restore/failure accounting mismatch")
        if tool == "smac":
            require(report["restored_trials"] == 6 and report["finished_trials"] == 12
                    and all(x["rejected"] for x in report["invalid_configuration_tests"]),
                    "SMAC restore/budget/constraint mismatch")
        if tool == "ytopt":
            require(report["actual_measurements"] == report["budget"] == 12
                    and report["out_of_order_verified"]
                    and report["each_result_token_and_config_verified"],
                    "ytopt asynchronous attribution mismatch")
        if tool == "ray-tune":
            require(report["restored_checkpoint_trials"] == report["total_trials"] == 3,
                    "Ray did not resume three genuine trial checkpoints")
            require(phase_counts["search"] == phase_counts["restored_trial"] == 3,
                    "Ray checkpoint phases lack six persisted real measurements")
        results[tool] = {
            "status": "passed", "report": str(result_path.relative_to(root)),
            "report_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "evaluations": len(rows), "valid_speeds": sum(bool(x["valid_speed"]) for x in rows),
            "failure_rows_without_speed": sum(not x["valid_speed"] for x in rows),
            "phase_counts": dict(phase_counts),
            "raw_measurement_files": [str(p.relative_to(root)) for p in evidence_files],
        }
    output = {"schema_version": 1, "status": "passed", "tools": results,
              "negative_controls": negative,
              "boundary": "Own JSON/JSONL reports use strict finite numbers. Upstream native state files are preserved in their original formats and are not treated as generic JSON."}
    Path(args.output).write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": "passed", "tools": len(results),
                      "actual_evaluations": sum(x["evaluations"] for x in results.values())}))


if __name__ == "__main__":
    main()
