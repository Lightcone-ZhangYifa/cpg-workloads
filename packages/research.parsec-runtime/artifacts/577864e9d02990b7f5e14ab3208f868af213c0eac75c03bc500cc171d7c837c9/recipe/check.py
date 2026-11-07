#!/usr/bin/env python3
"""Run two unmodified upstream CPU task graphs and check data and actual DAGs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

p = argparse.ArgumentParser()
p.add_argument("--runtime", required=True, type=Path)
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
a.runtime = a.runtime.resolve()
a.output = a.output.resolve()
a.output.mkdir(parents=True, exist_ok=True)
results = []
for name, values in (("ex02", list(range(11))), ("ex04", list(range(301, 322)))):
    for cores in (1, 2):
        case = f"{name}-cpu{cores}"
        graph_prefix = a.output / case
        for old_dot in a.output.glob(case + "-*.dot"):
            require(old_dot.is_file() and not old_dot.is_symlink(), ("Unexpected old graph path", old_dot))
            old_dot.unlink()
        argv = [str(a.runtime / "examples" / name), "--mca", "runtime_num_cores", str(cores),
                "--mca", "profile_dot", str(graph_prefix)]
        env = dict(os.environ)
        env.pop("LD_LIBRARY_PATH", None)  # exercise relative ELF RUNPATH
        env["PARSEC_MCA_param_files"] = ""
        run = subprocess.run(argv, cwd=a.output, env=env, text=True, capture_output=True, timeout=30)
        (a.output / (case + ".stdout.txt")).write_text(run.stdout)
        (a.output / (case + ".stderr.txt")).write_text(run.stderr)
        require(run.returncode == 0, (case, run.returncode, run.stderr))
        require("Error:" not in run.stderr and "command line error" not in run.stderr, run.stderr)
        got = [int(v) for v in re.findall(r"I am element (\d+) in the chain", run.stdout)]
        require(got == values, (case, got, values))
        dots = list(a.output.glob(case + "-*.dot"))
        require(len(dots) == 1, dots)
        text = dots[0].read_text()
        nodes = re.findall(r'^Task_(\d+)_(\d+) \[', text, re.M)
        edges = re.findall(r'^Task_(\d+)_(\d+) -> Task_(\d+)_(\d+) ', text, re.M)
        require(sorted(int(k) for _, k in nodes) == list(range(len(values))), nodes)
        actual_edges = [(int(x), int(y)) for _, x, _, y in edges]
        expected_edges = {(k, k + 1) for k in range(len(values) - 1)}
        require(len(actual_edges) == len(expected_edges), ("Duplicate or missing edges", edges))
        require(set(actual_edges) == expected_edges, ("Wrong dependency graph", edges))
        row = {"case": case, "returncode": run.returncode, "values": got,
               "task_nodes": len(nodes), "data_dependency_edges": len(edges),
               "runtime_dot": dots[0].name, "requested_cpu_threads": cores, "passed": True}
        results.append(row)
        print(json.dumps(row, sort_keys=True))
summary = {"status": "passed", "profile": "upstream-ex02-ex04-cpu-dataflow",
           "cases": results, "mpi_multi_rank": "not_run", "gpu": "not_run",
           "performance_claim": None, "upstream_source_modified": False}
(a.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
