#!/usr/bin/env python3
"""Installed Autograd check against analytic gradient, Jacobian and Hessian."""
from pathlib import Path
import math
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require

def functional(ag, work):
    """Check derivatives of scalar/vector functions and reject a nonscalar gradient."""
    np = installed_module("autograd.numpy")
    derivative = ag.grad(lambda x: np.sin(x) + x ** 3)
    for value in [-2.0, -0.25, 0.0, 1.5]:
        require(abs(derivative(value) - (math.cos(value) + 3 * value * value)) < 1e-12, "Analytic gradient mismatch")
    vector = np.array([2.0, 3.0])
    jacobian = ag.jacobian(lambda x: np.array([x[0] * x[1], np.sin(x[0])]))(vector)
    require(np.allclose(jacobian, [[3.0, 2.0], [math.cos(2.0), 0.0]], atol=1e-12, rtol=0), "Jacobian mismatch")
    quadratic = lambda x: x[0] ** 2 + 3 * x[0] * x[1] + 2 * x[1] ** 2
    hessian = ag.hessian(quadratic)(vector)
    require(np.allclose(hessian, [[2.0, 3.0], [3.0, 4.0]], atol=1e-12, rtol=0), "Hessian mismatch")
    require(np.allclose(ag.elementwise_grad(lambda x: x ** 3)(vector), [12.0, 27.0]), "Elementwise gradient mismatch")
    target = np.array([-1.0, 4.0]); objective = lambda x: np.sum((x - target) ** 2)
    updated = vector - 0.5 * ag.grad(objective)(vector)
    require(np.allclose(updated, target) and objective(updated) == 0, "Gradient update did not reach known minimizer")
    raises(TypeError, lambda: ag.grad(lambda x: np.array([x, x ** 2]))(2.0), "Nonscalar grad accepted")
    return {"checks": ["analytic-scalar-gradients", "vector-jacobian", "quadratic-hessian", "elementwise-gradient",
                       "known-minimizer-update", "nonscalar-gradient-error"], "scalar_cases": 4}

if __name__ == "__main__":
    raise SystemExit(main("autograd", "autograd", functional))
