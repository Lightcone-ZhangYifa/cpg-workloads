#!/usr/bin/env python3
"""Installed functional check for numpy; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(np, work):
    """Exercise arrays, a known linear system, storage and shape errors."""
    a = np.array([[3.0, 1.0], [1.0, 2.0]])
    b = np.array([9.0, 8.0])
    solution = np.linalg.solve(a, b)
    require(np.allclose(solution, [2.0, 3.0], atol=1e-12, rtol=0), "Linear solve mismatch")
    values = np.arange(6, dtype=np.int64).reshape(2, 3)
    require(np.array_equal(values + [10, 20, 30], [[10, 21, 32], [13, 24, 35]]), "Broadcast mismatch")
    target = work / "values.npy"
    np.save(target, values, allow_pickle=False)
    require(np.array_equal(np.load(target, allow_pickle=False), values), "Array file round trip mismatch")
    raises(ValueError, lambda: values.reshape(5), "Invalid shape was accepted")
    raises(np.linalg.LinAlgError, lambda: np.linalg.solve(np.zeros((2, 2)), b), "Singular matrix was accepted")
    return {"checks": ["broadcast", "linear-solve", "npy-roundtrip", "invalid-shape", "singular-system"], "solution": solution.tolist()}

if __name__ == "__main__":
    raise SystemExit(main('numpy', 'numpy', functional))
