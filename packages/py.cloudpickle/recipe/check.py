#!/usr/bin/env python3
"""Installed cloudpickle check for dynamic Python objects and process transfer."""
from pathlib import Path
import pickle
import sys
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, main, raises, require

def functional(cp, work):
    """Serialize closures/classes, load them in another process and reject bad input."""
    def factory(offset):
        return lambda value: value * 3 + offset
    function = factory(9)
    restored = cp.loads(cp.dumps(function))
    require([restored(x) for x in [-2, 0, 14]] == [3, 9, 51], "Closure serialization lost captured state")
    class Dynamic:
        def __init__(self, value): self.value = value
        def compute(self): return function(self.value)
    instance = cp.loads(cp.dumps(Dynamic(14)))
    require(instance.compute() == 51 and type(instance).__name__ == "Dynamic", "Dynamic class serialization failed")
    recursive = []; recursive.append(recursive)
    cycle = cp.loads(cp.dumps(recursive)); require(cycle[0] is cycle, "Object cycle was not preserved")
    payload = work / "closure.pkl"; payload.write_bytes(cp.dumps(function))
    consumer = work / "consumer.py"
    consumer.write_text("import cloudpickle, pathlib, sys\nf=cloudpickle.loads(pathlib.Path(sys.argv[1]).read_bytes())\nprint(f(14))\n")
    require(child([sys.executable, "-I", consumer, payload]).stdout == "51\n", "Cross-process closure transfer failed")
    raises((pickle.UnpicklingError, EOFError), lambda: cp.loads(b"not-a-pickle"), "Malformed pickle accepted")
    raises(TypeError, lambda: cp.dumps(threading.Lock()), "Unserializable lock accepted")
    return {"checks": ["captured-closure", "dynamic-class", "cyclic-object-identity", "separate-process-load",
                       "malformed-pickle", "unserializable-object"],
            "scope": "self-generated trusted objects only; unpickling is not a sandbox"}

if __name__ == "__main__":
    raise SystemExit(main("cloudpickle", "cloudpickle", functional))
