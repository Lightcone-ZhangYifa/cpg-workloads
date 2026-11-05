#!/usr/bin/env python3
"""Installed arbitrary-precision numerical checks with analytic references."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(mp, work):
    """Check high precision, quadrature, roots, differentiation and a linear solve."""
    old_precision = mp.mp.dps
    with mp.workdps(70):
        tolerance = mp.mpf("1e-60")
        require(abs(mp.sqrt(2) ** 2 - 2) < tolerance, "High-precision square root mismatch")
        require(abs(mp.quad(mp.sin, [0, mp.pi]) - 2) < tolerance, "Analytic integral mismatch")
        root = mp.findroot(lambda x: x ** 3 - 2, 1)
        require(abs(root ** 3 - 2) < tolerance, "Root residual too large")
        require(abs(mp.diff(mp.sin, 0) - 1) < tolerance, "Analytic derivative mismatch")
        solution = mp.lu_solve(mp.matrix([[3, 1], [1, 2]]), mp.matrix([9, 8]))
        require(max(abs(solution[0] - 2), abs(solution[1] - 3)) < tolerance, "Linear system mismatch")
        raises(ZeroDivisionError, lambda: mp.lu_solve(mp.matrix([[0, 0], [0, 0]]), mp.matrix([1, 1])),
               "Singular matrix accepted")
        rendered = mp.nstr(root, 65)
    require(mp.mp.dps == old_precision, "Precision context leaked")
    return {"checks": ["70-digit-arithmetic", "analytic-quadrature", "root-residual", "analytic-derivative",
                       "linear-system", "singular-matrix", "precision-context-restoration"], "cube_root_two": rendered}

if __name__ == "__main__":
    raise SystemExit(main("mpmath", "mpmath", functional))
