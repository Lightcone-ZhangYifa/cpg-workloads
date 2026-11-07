#!/usr/bin/env python3
"""Exercise the unchanged MSCCLang checker and lower a small all-reduce."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

require(sys.flags.optimize == 0, "Upstream checker uses assertions; Python optimization must be disabled")
p = argparse.ArgumentParser()
p.add_argument("--source", required=True, type=Path)
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
sys.path.insert(0, str(a.source.resolve()))
from msccl.language import MSCCLProgram, Buffer, chunk, Check, XML
from msccl.language.collectives import AllReduce
from msccl.topologies import fully_connected

a.output.mkdir(parents=True, exist_ok=True)
results = []
for size in (2, 3, 4):
    for broken in (False, True):
        name = f"allreduce_ring_{size}_{'missing_reduce' if broken else 'valid'}"
        with MSCCLProgram(name, fully_connected(size), AllReduce(size, size, inplace=True), 1):
            # Same ring construction as upstream examples/mscclang/simple/allreduce_ring.py.
            for rank in range(size):
                c = chunk(rank, Buffer.input, rank)
                nxt = (rank + 1) % size
                while nxt != rank:
                    other = chunk(nxt, Buffer.input, rank)
                    if broken and rank == 0 and nxt == 1:
                        c = c.copy(nxt, Buffer.input, rank)  # drop rank 1's contribution
                    else:
                        c = other.reduce(c)
                    nxt = (nxt + 1) % size
                while nxt != (rank - 1) % size:
                    c = c.copy(nxt, Buffer.input, rank)
                    nxt = (nxt + 1) % size
            check_output = io.StringIO()
            with contextlib.redirect_stdout(check_output):
                actual = Check()
            require(actual is (not broken), (name, actual))
            (a.output / (name + ".check.txt")).write_text(check_output.getvalue())
            row = {"case": name, "ranks": size, "expected_legal": not broken,
                   "official_Check": actual, "passed": True}
            if not broken:
                xml = io.StringIO()
                with contextlib.redirect_stdout(xml):
                    XML()
                text = xml.getvalue()
                root = ET.fromstring(text)
                require(len(root.findall("gpu")) == size, "XML GPU count does not match the topology")
                (a.output / (name + ".xml")).write_text(text)
                row["lowered_gpu_entries"] = len(root.findall("gpu"))
            results.append(row)
            print(json.dumps(row, sort_keys=True))
summary = {"profile": "software-allreduce-ring-2-3-4-ranks", "status": "passed",
           "upstream_checker": "msccl.language.Check", "cases": results,
           "gpu_runtime": "not_run", "multi_node_performance": "not_run"}
(a.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
