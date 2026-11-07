#!/usr/bin/env python3
"""TACCL's public topology/sketch/parser/checker surface; does not call Gurobi."""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

require(sys.flags.optimize == 0, "Upstream parser/checker uses assertions; Python optimization must be disabled")
p = argparse.ArgumentParser()
p.add_argument("--source", required=True, type=Path)
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
sys.path.insert(0, str(a.source.resolve()))
from taccl.topologies import dgx2, ndv2, TACCLTopology
# cli/__init__.py eagerly imports the licensed solver. Load the unchanged parser
# module by its path to exercise this independent public-data interface only.
parser_spec = importlib.util.spec_from_file_location("cpg_taccl_common", a.source / "taccl" / "cli" / "common.py")
parser_module = importlib.util.module_from_spec(parser_spec)
parser_spec.loader.exec_module(parser_module)
parse_and_get_topo = parser_module.parse_and_get_topo
from taccl.collectives import allgather
from taccl.algorithm import Algorithm, Step
from taccl.instance import Instance
from taccl.serialization import SCCLEncoder, SCCLDecoder

a.output.mkdir(parents=True, exist_ok=True)
examples = a.source / "taccl" / "examples"
rows = []
for path in sorted((examples / "topo").glob("*.json")):
    constructor = dgx2 if "dgx2" in path.name else ndv2
    topo = constructor(path)
    require(len(topo.links) in (8, 16), ("Unexpected upstream topology", path, len(topo.links)))
    rows.append({"asset": str(path.relative_to(a.source)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "kind": "upstream-topology", "gpus_per_node": len(topo.links), "parsed": True})
for path in sorted((examples / "sketch").glob("*.json")):
    is_dgx = "dgx2" in path.name
    base = (dgx2 if is_dgx else ndv2)(examples / "topo" / ("topo-dgx2-1MB.json" if is_dgx else "topo-ndv2-1MB.json"))
    with path.open() as f:
        topo, sketch = parse_and_get_topo(base, f)
    require(topo.num_nodes() in (8, 16, 32, 64), ("Unexpected sketch size", path, topo.num_nodes()))
    rows.append({"asset": str(path.relative_to(a.source)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "kind": "upstream-sketch", "logical_gpus": topo.num_nodes(), "parsed": True})

# A CPG-authored two-rank all-gather fixture, explicitly not a solver-produced result.
topo = TACCLTopology("cpg-two-rank", 1, 2, [[0, 1], [1, 0]], [[0, 1], [1, 0]],
                     -1, -1, None, None)
collective = allgather(2)
algo = Algorithm.make_implementation(collective, topo, Instance(1),
                                     [Step(1, [(0, 0, 1), (1, 1, 0)])])
encoded = SCCLEncoder().encode(algo)
(a.output / "two-rank-allgather.json").write_text(encoded + "\n")
decoded = SCCLDecoder().decode(encoded)
decoded.check_implements(collective)
require(decoded.num_steps() == 1, "Schedule did not preserve its step count")
require(decoded.steps[0].sends == [(0, 0, 1), (1, 1, 0)], "Schedule did not preserve its transfers")
rows.append({"case": "CPG-authored-schedule-roundtrip", "parsed": True,
             "official_implementation_check": True, "solver_generated": False})

bad = json.loads(encoded)
bad["steps"][0]["sends"] = [[0, 0, 1]]
(a.output / "two-rank-invalid.json").write_text(json.dumps(bad, indent=2) + "\n")
try:
    invalid = SCCLDecoder().decode(json.dumps(bad))
    invalid.check_implements(collective)
except RuntimeError as e:
    require("postcondition" in str(e), ("Unexpected checker error", str(e)))
    (a.output / "missing-transfer-rejection.txt").write_text(str(e) + "\n")
else:
    raise AssertionError("upstream checker did not reject missing all-gather transfer")

example = examples / "sketch" / "sk1-dgx2-n2.json"
bad_sketch = json.loads(example.read_text())
bad_sketch["intranode_sketch"]["strategy"] = "invalid-strategy"
try:
    parse_and_get_topo(dgx2(examples / "topo" / "topo-dgx2-1MB.json"), io.StringIO(json.dumps(bad_sketch)))
except AssertionError as e:
    require("No such intranode strategy" in str(e), ("Unexpected parser error", str(e)))
    (a.output / "invalid-sketch-rejection.txt").write_text(str(e) + "\n")
else:
    raise AssertionError("upstream parser accepted an unknown sketch strategy")
summary = {"status": "passed", "profile": "topology-sketch-schedule-parsing-and-checking",
           "upstream_assets_parsed": len(rows) - 1, "checks": rows,
           "negative_controls": ["missing-allgather-transfer", "unknown-sketch-strategy"],
           "gurobi_solver": "not_run; no licensed environment supplied",
           "gpu_execution": "not_run", "schedule_fixture_origin": "CPG-authored, not author evaluation schedule"}
(a.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "checks"}, sort_keys=True))
