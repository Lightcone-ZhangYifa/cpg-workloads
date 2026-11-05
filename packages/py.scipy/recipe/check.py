#!/usr/bin/env python3
"""Installed functional check for scipy; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(scipy, work):
    """Check numerical results against analytic answers and reject bad shapes."""
    import math
    np = installed_module("numpy")
    from scipy import integrate, linalg, optimize, sparse
    solution = linalg.solve([[3.0, 1.0], [1.0, 2.0]], [9.0, 8.0])
    require(np.allclose(solution, [2.0, 3.0], atol=1e-12, rtol=0), "Dense solve mismatch")
    matrix = sparse.csr_matrix([[2, 0], [0, 3]])
    require(np.array_equal(matrix @ np.array([4, 5]), [8, 15]), "Sparse multiply mismatch")
    integral, error = integrate.quad(lambda x: x*x, 0.0, 1.0)
    require(abs(integral - 1/3) < 1e-12 and error >= 0, "Quadrature mismatch")
    root = optimize.brentq(lambda x: x*x-2, 0, 2)
    require(abs(root-math.sqrt(2)) < 1e-12, "Root mismatch")
    raises(ValueError, lambda: linalg.solve([[1, 2, 3]], [1]), "Non-square solve was accepted")
    return {"checks": ["dense-solve", "sparse-multiply", "quadrature", "bracketed-root", "invalid-shape"], "integral": integral, "root": root}

if __name__ == "__main__":
    raise SystemExit(main('scipy', 'scipy', functional))
