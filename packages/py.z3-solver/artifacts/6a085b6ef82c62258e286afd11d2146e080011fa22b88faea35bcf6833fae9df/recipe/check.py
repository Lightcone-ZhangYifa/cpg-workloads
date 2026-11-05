#!/usr/bin/env python3
"""Installed functional check for z3-solver; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(z3, work):
    """Check satisfiable and unsatisfiable systems and a bit-vector identity."""
    x, y = z3.Ints("x y")
    solver = z3.Solver()
    solver.add(x+y == 7, x-y == 1)
    require(solver.check() == z3.sat, "Known satisfiable system was rejected")
    model = solver.model()
    require((model[x].as_long(), model[y].as_long()) == (4, 3), "Model oracle mismatch")
    solver.push()
    solver.add(x < 0)
    require(solver.check() == z3.unsat, "Contradictory system was accepted")
    solver.pop()
    require(solver.check() == z3.sat, "Solver scope did not restore")
    bits = z3.BitVec("bits", 8)
    proof = z3.Solver()
    proof.add(bits + z3.BitVecVal(0, 8) != bits)
    require(proof.check() == z3.unsat, "Bit-vector identity was not established")
    raises(z3.Z3Exception, lambda: z3.Solver().model(), "Model before check was accepted")
    return {"checks": ["sat-and-model", "unsat", "push-pop", "bitvector-identity", "model-before-check"]}

if __name__ == "__main__":
    raise SystemExit(main('z3-solver', 'z3', functional))
