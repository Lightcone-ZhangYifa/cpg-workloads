#!/usr/bin/env python3
"""Installed joblib check using real process workers and a local persistent cache."""
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def squared_with_process(value):
    return value * value, os.getpid()

def functional(joblib, work):
    """Check compressed persistence, cache hits, process jobs and propagated errors."""
    data = {"values": list(range(8)), "nested": ("compiler", b"\x00\xff")}
    path = work / "object.joblib"
    joblib.dump(data, path, compress=3)
    require(joblib.load(path) == data, "Compressed object round trip failed")
    require(joblib.hash(data) == joblib.hash(dict(data)) and joblib.hash(data) != joblib.hash({"values": []}),
            "Object hash equality/difference failed")
    counter = work / "executions.txt"
    def expensive(value):
        with counter.open("a") as stream: stream.write("executed\n")
        return value * value
    memory = joblib.Memory(work / "cache", verbose=0)
    cached = memory.cache(expensive)
    require(cached(7) == cached(7) == 49 and counter.read_text().splitlines() == ["executed"], "Cache did not reuse the result")
    cached.clear(warn=False)
    require(cached(7) == 49 and len(counter.read_text().splitlines()) == 2, "Cache clear did not force recomputation")
    with joblib.Parallel(n_jobs=2, backend="loky") as pool:
        rows = pool(joblib.delayed(squared_with_process)(x) for x in range(8))
    require([x[0] for x in rows] == [x * x for x in range(8)], "Parallel result order/value mismatch")
    require(all(pid != os.getpid() for _, pid in rows), "Process backend silently executed in the parent")
    def fail(): raise ValueError("cpg-known-task-error")
    raises(ValueError, lambda: joblib.Parallel(n_jobs=2, backend="loky")([joblib.delayed(fail)()]),
           "Worker exception was not propagated")
    raises(ValueError, lambda: joblib.Parallel(n_jobs=0)([]), "Invalid job count accepted")
    raises(FileNotFoundError, lambda: joblib.load(work / "missing.joblib"), "Missing file accepted")
    return {"checks": ["compressed-persistence", "object-hash", "cache-hit", "cache-invalidation",
                       "real-process-workers", "ordered-results", "worker-error", "invalid-job-count", "missing-file"],
            "process_ids": sorted(set(pid for _, pid in rows)), "tasks": len(rows)}

if __name__ == "__main__":
    raise SystemExit(main("joblib", "joblib", functional))
