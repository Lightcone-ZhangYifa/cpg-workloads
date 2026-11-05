"""Check one installed reference resource against its independent recipe oracle."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check(reader, prefix: Path, contract: dict, kind: str) -> dict:
    verified = reader.verify()
    entity, version, commit = (contract[name] for name in ("entity_id", "version", "commit"))
    require((verified["entity_id"], verified["version"], verified["commit"]) == (entity, version, commit),
            "Installed resource identity differs from the independent recipe")
    require(verified["assets"] == 1 and verified["source_files"] == contract["source_files"]
            and verified["payload_files"] == contract["payload_files"]
            and verified["inventory_sha256"] == contract["inventory_sha256"]
            and verified["integrity_mode"] == "externally_anchored", "Installed material contract differs")
    require(sorted(reader.sources) == contract["source_paths"], "Package contains another resource's source files")
    result = {"status": "passed", "kind": kind, "entity_id": entity, "version": version, "commit": commit,
              "scope": "installed single-resource reference reader only", "inventory": verified,
              "upstream_tool_executions": 0, "upstream_functional_qualification": None,
              "official_benchmark": None, "dataset_verified": None}
    if kind == "availability":
        return result
    require(kind == "functional", "Unknown qualification kind")
    results = []
    for case in contract["oracles"]:
        raw = (prefix / "materials" / case["path"]).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == case["sha256"], "Fixed upstream source digest differs")
        require(raw.decode("utf-8").splitlines()[case["line"] - 1] == case["text"], "Fixed upstream source line differs")
        hits = reader.search(case["query"], asset=entity, limit=20)
        hits = [row for row in hits if row["upstream_path"] == case["path"] and row["line"] == case["line"]]
        expected = {"entity_id": entity, "version": version, "commit": commit, "upstream_path": case["path"],
                    "line": case["line"], "text": case["text"], "source_sha256": case["sha256"],
                    "source_url": f"https://github.com/llvm/llvm-project/blob/{commit}/{case['path']}#L{case['line']}"}
        require(hits == [expected], "Search did not return the exact independently pinned source line")
        excerpt = reader.read(hits[0]["upstream_path"], line=hits[0]["line"], count=1)
        require(excerpt == {"entity_id": entity, "version": version, "commit": commit,
                            "upstream_path": case["path"], "line": case["line"], "end_line": case["line"],
                            "lines": [{"line": case["line"], "text": case["text"]}], "source_sha256": case["sha256"]},
                "Read did not return the exact independently pinned source line")
        results.append({"query": case["query"], "search": hits[0], "read": excerpt})
    require(bool(results), "A functional reference check needs an independent source oracle")
    for expectation in contract.get("index_expectations", []):
        rows = reader.index(kind=expectation["kind"])
        if "count" in expectation:
            require(len(rows) == expectation["count"], "Static source index count differs")
        for field, value in expectation.get("all_fields", {}).items():
            require(all(row.get(field) == value for row in rows), "Static index semantics differ")
    index_queries = []
    for expectation in contract.get("index_queries", []):
        rows = getattr(reader, expectation["method"])(expectation["query"], limit=20)
        require(any(all(row.get(key) == value for key, value in expectation["match"].items()) for row in rows),
                "Index query did not locate the independently pinned declaration")
        index_queries.append({"query": expectation["query"], "results": rows})
    require(reader.search("CPG_ABSENT_REFERENCE_QUERY_2ba6eb01", asset=entity) == [], "Absent query returned invented evidence")
    for action in (lambda: reader.search("x", asset="reference.doc.not-installed"),
                   lambda: reader.read("../source-lock.json"),
                   lambda: reader.read(contract["oracles"][0]["path"], line=0)):
        try:
            action()
        except ValueError:
            pass
        else:
            raise ValueError("Reader accepted a foreign asset, escaped path or invalid line")
    result.update(cases=results, index_queries=index_queries, index_expectations=contract.get("index_expectations", []),
                  absent_query_empty=True, foreign_asset_rejected=True, invalid_reads_rejected=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--kind", choices=("availability", "functional"), required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("installed_reference_reader", args.prefix / "reference_reader.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    contract = json.loads(args.contract.read_text())
    reader = module.ReferenceReader(args.prefix, expected_inventory_sha256=contract["inventory_sha256"])
    print(json.dumps(check(reader, args.prefix, contract, args.kind), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
