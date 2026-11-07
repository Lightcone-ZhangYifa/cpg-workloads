#!/usr/bin/env python3
"""Use TrainVerify's real shape reducer, operators and Z3 verifier on tiny DFGs.

The JSON DFG adapter is a new input adapter, not the nnScaler graph-capture path.
No upstream checker or solver implementation is replaced.
"""
import argparse
import json
from pathlib import Path
import sys

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

require(sys.flags.optimize == 0, "Upstream verifier uses assertions; Python optimization must be disabled")
p = argparse.ArgumentParser()
p.add_argument("--source", required=True, type=Path)
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
sys.path.insert(0, str((a.source / "Verdict").resolve()))
from verdict.graph import DFG, World, WType, DTag, Lineage
from verdict.operators import OpName
from verdict.stage import Stage, run_stage
from verdict.config import Config
from verdict.report import report
from verdict.log import setup_logger
from z3_backend import z3Backend
import z3

a.output.mkdir(parents=True, exist_ok=True)
Config.time = False
Config.mem = False
setup_logger("INFO")
z3.set_param("smt.random_seed", 0)

class TinyGraph(DFG):
    def __init__(self, data):
        self.data = data
        self.by_id = {n["id"]: n for n in data["nodes"]}
        self._node2irstr = {}  # optional upstream diagnostic field
    @property
    def ID(self): return self.data["id"]
    @property
    def W(self):
        return World(wtype=WType(self.data["world"]), num_dp=1, num_tp=2,
                     num_pp=1, num_mb=1, model_name="tiny_linear_tp2")
    def nodes(self): return list(self.by_id)
    def node_dtag(self, node): return DTag(0, 0, 0, 0, 0)
    def node_kwargs(self, node): return self.by_id[node].get("kwargs", {})
    def node_inputs(self, node): return self.by_id[node]["inputs"]
    def node_outputs(self, node): return self.by_id[node]["outputs"]
    def node_opname(self, node): return OpName[self.by_id[node]["op"]]
    def tensors(self): return list(self.data["shapes"])
    def tensor_shape(self, tensor): return tuple(self.data["shapes"][tensor])
    def is_initialized(self, tensor): return tensor in self.data["inputs"]

def node(name, op, ins, outs, **kwargs):
    return {"id": name, "op": op, "inputs": ins, "outputs": outs, "kwargs": kwargs}

def lineage(t, copies, shape, slices):
    out = Lineage(t, set(copies))
    out.full_shape = shape
    out.slice_map = slices
    return out

single = {"id": "single-linear", "world": "s", "inputs": ["s.x", "s.w"],
          "shapes": {"s.x": [2, 4], "s.w": [2, 4], "s.y": [2, 2]},
          "nodes": [node("s.linear", "FW_linear", ["s.x", "s.w"], ["s.y"], bias=None)]}
parallel = {"id": "parallel-linear-allreduce", "world": "p",
            "inputs": ["p.x0", "p.x1", "p.w0", "p.w1"],
            "shapes": {name: [2, 2] for name in ["p.x0", "p.x1", "p.w0", "p.w1",
                                                "p.partial0", "p.partial1", "p.y0", "p.y1"]},
            "nodes": [node("p.linear0", "FW_linear", ["p.x0", "p.w0"], ["p.partial0"], bias=None),
                      node("p.linear1", "FW_linear", ["p.x1", "p.w1"], ["p.partial1"], bias=None),
                      node("p.allreduce0", "AllReducePrim", ["p.partial0", "p.partial1"], ["p.y0"]),
                      node("p.allreduce1", "AllReducePrim", ["p.partial0", "p.partial1"], ["p.y1"])]}
inputs = []
for name in ("x", "w"):
    inputs.append(lineage("s." + name, ["p." + name + "0", "p." + name + "1"], [2, 4],
                          {((0, 2), (0, 2)): [["p." + name + "0"]],
                           ((0, 2), (2, 4)): [["p." + name + "1"]]}))
outputs = [lineage("s.y", ["p.y0", "p.y1"], [2, 2],
                   {((0, 2), (0, 2)): [["p.y0"], ["p.y1"]]})]
(a.output / "single.json").write_text(json.dumps(single, indent=2) + "\n")
(a.output / "parallel-valid.json").write_text(json.dumps(parallel, indent=2) + "\n")
Gs, Gp = TinyGraph(single), TinyGraph(parallel)
stage = Stage(0, Gs.nodes(), Gp.nodes(), inputs, outputs)
require(run_stage(stage, Gs, Gp, z3Backend), "Valid tensor-parallel graph was rejected")
positive = {"case": "sharded-linear-plus-allreduce", "equivalent": True,
            "engine": "TrainVerify.run_stage / z3Backend"}
print(json.dumps(positive))

# Remove one participant from one collective, while retaining the correct output lineage.
broken = json.loads(json.dumps(parallel))
broken["id"] = "parallel-missing-contribution"
broken["nodes"][2]["inputs"] = ["p.partial0"]
(a.output / "parallel-invalid.json").write_text(json.dumps(broken, indent=2) + "\n")
bad_graph = TinyGraph(broken)
bad_stage = Stage(1, Gs.nodes(), bad_graph.nodes(), inputs, outputs)
try:
    run_stage(bad_stage, Gs, bad_graph, z3Backend)
except RuntimeError as e:
    require("equivalence fails" in str(e), ("Unexpected checker error", str(e)))
    require(report.sat == z3.sat, ("Expected a satisfiable counterexample", report.sat))
    counterexample = report.dump_z3()
    require("p.y0" in counterexample, "Counterexample did not include the wrong collective output")
    (a.output / "counterexample.txt").write_text(counterexample + "\n")
    (a.output / "counterexample.model.txt").write_text(str(report.model) + "\n")
else:
    raise AssertionError("TrainVerify accepted the incorrect AllReduce")
negative = {"case": "missing-allreduce-contribution", "equivalent": False,
            "solver_result": "sat", "counterexample": "counterexample.txt"}
print(json.dumps(negative))
summary = {"status": "passed", "profile": "tiny-dual-DFG-linear-tensor-parallel-allreduce",
           "z3_version": z3.get_version_string(), "positive": positive, "negative": negative,
           "official_mlp_capture": "not_run; requires torch/nnScaler GPU capture",
           "input_adapter": "CPG TinyGraph implements upstream DFG; graphs are explicit local fixtures",
           "upstream_semantics_modified": False, "distributed_training_execution": "not_run"}
(a.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
