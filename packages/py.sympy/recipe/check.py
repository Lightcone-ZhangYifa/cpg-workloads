#!/usr/bin/env python3
"""Installed functional check for sympy; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(sp, work):
    """Use exact algebraic oracles without floating-point approximations."""
    x = sp.Symbol("x")
    require(sp.diff(x**3 + 2*x, x) == 3*x**2+2, "Derivative mismatch")
    require(sp.factor(x*x-1) == (x-1)*(x+1), "Factorization mismatch")
    require(sp.solve(x*x-4, x) == [-2, 2], "Equation roots mismatch")
    require(sp.integrate(x*x, (x, 0, 1)) == sp.Rational(1, 3), "Exact integral mismatch")
    require(sp.Matrix([[1, 2], [3, 4]]).det() == -2, "Determinant mismatch")
    raises(sp.matrices.exceptions.NonInvertibleMatrixError, lambda: sp.zeros(2).inv(), "Singular inverse was accepted")
    return {"checks": ["differentiate", "factor", "solve", "exact-integral", "matrix", "singular-inverse"]}

if __name__ == "__main__":
    raise SystemExit(main('sympy', 'sympy', functional))
