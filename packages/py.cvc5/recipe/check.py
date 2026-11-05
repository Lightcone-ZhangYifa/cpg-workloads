#!/usr/bin/env python3
"""Installed cvc5 check with integer and bit-vector known answers."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(cvc5, work):
    """Check models, SAT/UNSAT, incremental scopes, a bit-vector theorem and sorts."""
    K = cvc5.Kind
    tm = cvc5.TermManager(); solver = cvc5.Solver(tm)
    solver.setLogic("QF_LIA"); solver.setOption("produce-models", "true"); solver.setOption("incremental", "true")
    x = tm.mkConst(tm.getIntegerSort(), "x"); y = tm.mkConst(tm.getIntegerSort(), "y")
    solver.assertFormula(tm.mkTerm(K.EQUAL, tm.mkTerm(K.ADD, x, y), tm.mkInteger(11)))
    solver.assertFormula(tm.mkTerm(K.EQUAL, tm.mkTerm(K.SUB, x, y), tm.mkInteger(3)))
    require(solver.checkSat().isSat(), "Known integer system was not SAT")
    require(str(solver.getValue(x)) == "7" and str(solver.getValue(y)) == "4", "Wrong integer model")
    solver.push(); solver.assertFormula(tm.mkTerm(K.LT, x, tm.mkInteger(0)))
    require(solver.checkSat().isUnsat(), "Contradictory scope was not UNSAT")
    solver.pop(); require(solver.checkSat().isSat(), "Pop did not restore the satisfiable context")
    bv = cvc5.Solver(tm); bv.setLogic("QF_BV"); bv.setOption("produce-models", "true")
    b = tm.mkConst(tm.mkBitVectorSort(8), "b")
    bv.assertFormula(tm.mkTerm(K.EQUAL, tm.mkTerm(K.BITVECTOR_ADD, b, tm.mkBitVector(8, 1)), tm.mkBitVector(8, 0)))
    require(bv.checkSat().isSat() and int(bv.getValue(b).getBitVectorValue(10)) == 255, "Wrong modular-overflow model")
    theorem = cvc5.Solver(tm); theorem.setLogic("QF_BV")
    v = tm.mkConst(tm.mkBitVectorSort(8), "v")
    twice = tm.mkTerm(K.BITVECTOR_ADD, v, v)
    multiply = tm.mkTerm(K.BITVECTOR_MULT, v, tm.mkBitVector(8, 2))
    theorem.assertFormula(tm.mkTerm(K.NOT, tm.mkTerm(K.EQUAL, twice, multiply)))
    require(theorem.checkSat().isUnsat(), "8-bit doubling equivalence was not proved")
    raises(RuntimeError, lambda: tm.mkTerm(K.ADD, x, tm.mkBoolean(True)), "Mixed integer/boolean addition accepted")
    return {"checks": ["integer-sat", "exact-model", "incremental-unsat", "pop-restores-sat",
                       "bitvector-wraparound", "unconstrained-bitvector-theorem", "sort-error"], "integer_model": [7, 4]}

if __name__ == "__main__":
    raise SystemExit(main("cvc5", "cvc5", functional))
