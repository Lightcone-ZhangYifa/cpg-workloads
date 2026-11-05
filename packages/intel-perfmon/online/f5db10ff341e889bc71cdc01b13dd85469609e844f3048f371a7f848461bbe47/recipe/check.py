#!/usr/bin/env python3
"""Validate local Intel event tables or report whether this CPU has a map entry."""
import argparse
import csv
import fnmatch
import json
from pathlib import Path


def map_rows(prefix):
    prefix = prefix.resolve()
    rows = []
    mapping = prefix / "mapfile.csv"
    if mapping.is_symlink():
        raise ValueError("The installed CPU event map must be a regular package file")
    with mapping.open(encoding="utf-8-sig", newline="") as stream:
        for number, row in enumerate(csv.reader(stream), 1):
            if not row or row[0].startswith("Family-model"):
                continue
            if len(row) < 4 or not row[0]:
                raise ValueError("Malformed CPU event-map row " + str(number))
            relative = Path(row[2].lstrip("/"))
            payload = prefix / relative
            if not relative.parts or ".." in relative.parts or not payload.resolve().is_relative_to(prefix):
                raise ValueError("CPU event-map path escapes the package")
            if not payload.is_file() or payload.is_symlink():
                raise ValueError("Missing or symlinked event table: " + str(relative))
            rows.append((row[0], str(relative), row[3]))
    if not rows:
        raise ValueError("The CPU event map contains no resource rows")
    return rows


def validate_tables(prefix):
    rows = map_rows(prefix)
    paths = sorted({row[1] for row in rows})
    for relative in paths:
        data = json.loads((prefix / relative).read_text())
        if not isinstance(data, (list, dict)) or not data:
            raise ValueError("An event table is empty or has an invalid JSON shape: " + relative)
    return {"cpu_map_rows": len(rows), "json_tables": len(paths)}


def cpu_identifiers(text):
    identifiers = set()
    for block in text.split("\n\n"):
        fields = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        fields = {key.strip(): value.strip() for key, value in fields.items()}
        if fields.get("vendor_id") != "GenuineIntel":
            continue
        base = "GenuineIntel-" + format(int(fields["cpu family"]), "X") + "-" + format(int(fields["model"]), "02X")
        identifiers.update((base, base + "-" + format(int(fields["stepping"]), "X")))
    return sorted(identifiers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("tables", "cpu-match"))
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "tables":
            detail = validate_tables(args.prefix)
        else:
            ids = cpu_identifiers(Path("/proc/cpuinfo").read_text())
            matches = sorted({path for pattern, path, _ in map_rows(args.prefix)
                              if any(fnmatch.fnmatchcase(cpu, pattern) for cpu in ids)})
            if not matches:
                print(json.dumps({"status": "blocked", "check": "intel-perfmon-cpu-map",
                                  "reason": "No map entry for the visible CPU identity", "cpu_ids": ids}))
                return 77
            detail = {"cpu_ids": ids, "mapped_tables": matches, "counter_collection_qualified": False}
        print(json.dumps({"status": "passed", "check": args.mode, "details": detail}))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "failed", "check": args.mode, "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
