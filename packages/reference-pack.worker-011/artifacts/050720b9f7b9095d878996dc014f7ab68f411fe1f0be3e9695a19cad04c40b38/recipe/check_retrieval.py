"""Exercise the installed reference reader against fixed upstream text.

This qualifies local reference retrieval, not LLVM/MLIR execution, benchmark
results, or the historical qualifications of the four reference entities.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

INVENTORY_SHA256 = "979134ffdffc1cae9b48b8b72b2db036465f47ad23f653307a9f47fdfa04dac4"
COMMIT = "87f0227cb60147a26a1eeb4fb06e3b505e9c7261"
CASES = (
    {"asset": "reference.doc.openmp-opt", "query": "globalization",
     "path": "openmp/docs/optimizations/OpenMPOpt.rst", "line": 39,
     "text": "Globalization",
     "sha256": "52751bb177913a8a6199be7813dce1c8e96de888e12006daf45e5e06c80a6ec1"},
    {"asset": "reference.doc.llvm-remarks", "query": "Hotness",
     "path": "llvm/docs/Remarks.rst", "line": 125,
     "text": "    .. option:: -pass-remarks-with-hotness",
     "sha256": "a066d7cee458f3a247428216efee5239d912c5231155e1353f4f472e280dfe42"},
    {"asset": "reference.doc.llvm-testsuite", "query": "TEST_SUITE_BENCHMARKING_ONLY",
     "path": "llvm/docs/TestSuiteGuide.md", "line": 149,
     "text": "performance measurements. Setting the `TEST_SUITE_BENCHMARKING_ONLY` CMake",
     "sha256": "0c45316accbe149d30a4e7affeb15cd41bbe4e65f4b8bd1b7300b4da63db9e83"},
    {"asset": "reference.doc.mlir-sparse", "query": "sparse_tensor.convert",
     "path": "mlir/include/mlir/Dialect/SparseTensor/IR/SparseTensorOps.td", "line": 187,
     "text": "    %0 = sparse_tensor.convert %a : tensor<32x32xf32> to tensor<32x32xf32, #CSR>",
     "sha256": "4be00630afad25c40fc0f6835d18ae814cfae58cb65679866bb01a9576b45172"},
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_retrieval(library, prefix: Path) -> dict:
    material = library.verify()
    require(material["status"] == "passed" and material["commit"] == COMMIT,
            "Reader material identity differs from the fixed source commit")
    require(material["inventory_sha256"] == INVENTORY_SHA256,
            "Reader inventory differs from the externally bound recipe")
    observed = []
    for case in CASES:
        source = prefix / "materials" / "upstream" / case["path"]
        raw = source.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == case["sha256"],
                "Fixed upstream source digest differs: " + case["path"])
        require(raw.decode("utf-8").splitlines()[case["line"] - 1] == case["text"],
                "Fixed upstream source line differs: " + case["path"])
        hits = library.search(case["query"], asset_id=case["asset"], limit=8)
        matches = [hit for hit in hits
                   if hit["upstream_path"] == case["path"] and hit["line"] == case["line"]]
        require(len(matches) == 1, "Search did not locate the expected original line: " + case["asset"])
        hit = matches[0]
        require(hit["asset_ids"] == [case["asset"]], "Search attributed the line to the wrong asset")
        require(hit["text"] == case["text"] and hit["source_sha256"] == case["sha256"],
                "Search content or source identity differs")
        expected_url = f"https://github.com/llvm/llvm-project/blob/{COMMIT}/{case['path']}#L{case['line']}"
        require(hit["source_url"] == expected_url, "Search returned a mutable or incorrect source locator")
        excerpt = library.read(hit["upstream_path"], line=hit["line"], count=1)
        require(excerpt == {
            "upstream_path": case["path"], "line": case["line"], "end_line": case["line"],
            "lines": [{"line": case["line"], "text": case["text"]}],
            "source_sha256": case["sha256"],
        }, "Read did not reproduce the exact source line and identity")
        observed.append({"asset": case["asset"], "query": case["query"],
                         "matching_hit": hit, "read_result": excerpt})
    require(library.search("CPG_WORKER011_QUERY_MUST_NOT_EXIST_6ffca7c4") == [],
            "An absent query unexpectedly returned a match")
    try:
        library.read("../LICENSE")
    except ValueError:
        pass
    else:
        raise ValueError("The reader accepted traversal outside its source set")
    return {"status": "passed", "scope": "installed reference-reader functionality only",
            "assets_exercised": len(observed), "cases": observed,
            "absent_query_rejected": True, "path_traversal_rejected": True,
            "upstream_tool_executions": 0, "upstream_functional_qualification": None,
            "official_benchmark": None, "dataset_verified": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    prefix = args.prefix.absolute()
    spec = importlib.util.spec_from_file_location("worker011_installed_reference", prefix / "reference_library.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    library = module.ReferenceLibrary(prefix, expected_inventory_sha256=INVENTORY_SHA256)
    print(json.dumps(check_retrieval(library, prefix), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
