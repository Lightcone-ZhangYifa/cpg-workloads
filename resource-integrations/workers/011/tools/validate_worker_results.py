"""Validate worker result rows without changing the original coverage denominator."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path, PurePosixPath

FIELDS = "schema_version,plan_id,worker_id,record_id,entity_kind,entity_id,baseline_version,result_status,before_material,before_functional,before_dataset_verified,after_material,after_functional,after_dataset_verified,evidence_relpath,increment_package,notes".split(",")
PLAN = "cpg-resource-research-20261101-v1"


def validate(bundles: list[Path], assignments: list[dict]) -> dict:
    expected = {r["record_id"]: r for r in assignments}
    seen, records, results = set(), set(), []
    for root in bundles:
        for line in (root / "worker-results.jsonl").read_text().splitlines():
            if not line.strip():
                raise ValueError("Blank result rows are not accepted")
            row = json.loads(line)
            if set(row) != set(FIELDS):
                raise ValueError("Result fields differ from the shared template")
            if type(row["schema_version"]) is not int or row["schema_version"] != 1 or row["plan_id"] != PLAN:
                raise ValueError("Result schema or plan identity mismatch")
            task = expected[row["record_id"]]
            if row["worker_id"] != task["worker_id"] or row["entity_kind"] != task["entity_kind"]:
                raise ValueError("Result does not belong to its assigned task")
            if row["baseline_version"] != "0.21.14" or row["increment_package"] != task["increment_package"]:
                raise ValueError("Baseline or increment package identity mismatch")
            if not isinstance(row["entity_id"], str) or not row["entity_id"]:
                raise ValueError("Missing exact entity ID")
            expected_entity = (task["record_id"] if task["entity_kind"] == "reference_asset"
                               else "bindings." + task["record_id"].removeprefix("review.engineering."))
            if row["entity_id"] != expected_entity:
                raise ValueError("Resolved entity ID differs from the exact assigned identity")
            for field in FIELDS:
                if field.startswith(("before_", "after_")):
                    if row[field] is not None and type(row[field]) is not bool:
                        raise ValueError("Qualification must be boolean or null: " + field)
            if any(row[key] is not None for key in ("before_material", "before_functional", "before_dataset_verified")):
                raise ValueError("Unobserved pre-task qualification must remain null")
            key = (row["plan_id"], row["entity_kind"], row["entity_id"])
            if key in seen or row["record_id"] in records:
                raise ValueError("Duplicate result identity: " + repr(key))
            seen.add(key)
            records.add(row["record_id"])
            relative = PurePosixPath(row["evidence_relpath"])
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != row["evidence_relpath"]:
                raise ValueError("Invalid evidence path")
            evidence = root / relative
            if not evidence.is_file() or evidence.is_symlink():
                raise ValueError("Missing ordinary evidence file: " + str(evidence))
            if row["entity_kind"] == "reference_asset":
                if row["after_material"] is not True or row["after_functional"] is not None or row["after_dataset_verified"] is not None:
                    raise ValueError("Reference material has incorrect qualification flags")
            elif row["entity_kind"] == "resource":
                if row["after_functional"] is not True or row["after_material"] is not True or row["after_dataset_verified"] is not None:
                    raise ValueError("The expected binding profile is not complete")
            results.append(row)
    if records != set(expected):
        raise ValueError("Result rows and exact assigned record IDs differ")
    return {"schema_version": 1, "status": "passed", "plan_id": PLAN,
            "result_rows": len(results), "unique_result_keys": len(seen),
            "workers": dict(Counter(r["worker_id"] for r in results)),
            "entity_kinds": dict(Counter(r["entity_kind"] for r in results)),
            "reference_assets_verified": sum(r["entity_kind"] == "reference_asset" for r in results),
            "new_binding_profiles_verified": sum(r["entity_kind"] == "resource" for r in results),
            "original_resource_denominator": 1862, "original_managed_resources": 1703,
            "original_managed_increment": 0, "dataset_increment": 0,
            "note": "Reference subassets and four new bindings are counted separately from the unchanged original-resource coverage."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, action="append", required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw_assignments = args.assignments.read_text()
    try:
        assignments = json.loads(raw_assignments)
    except json.JSONDecodeError:
        assignments = [json.loads(line) for line in raw_assignments.splitlines() if line.strip()]
    if isinstance(assignments, dict):
        assignments = [assignments]
    result = validate(args.bundle, assignments)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
