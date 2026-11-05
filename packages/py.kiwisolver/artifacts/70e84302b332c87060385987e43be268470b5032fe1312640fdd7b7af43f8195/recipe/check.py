#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(kiwi, work):
    """Check linear constraints, edits, priority and constraint error contracts."""
    solver = kiwi.Solver(); x = kiwi.Variable('x'); y = kiwi.Variable('y')
    total = x + y == 12; ratio = x == 2 * y
    solver.addConstraint(total); solver.addConstraint(ratio); solver.updateVariables()
    require(abs(x.value()-8) < 1e-12 and abs(y.value()-4) < 1e-12, 'Linear system answer wrong')
    raises(kiwi.DuplicateConstraint, lambda: solver.addConstraint(total), 'Duplicate constraint accepted')
    solver.removeConstraint(ratio); fixed = x == 6; solver.addConstraint(fixed); solver.updateVariables()
    require(x.value() == y.value() == 6, 'Constraint removal/replacement failed')
    raises(kiwi.UnsatisfiableConstraint, lambda: solver.addConstraint(x == 8), 'Inconsistent required constraint accepted')
    raises(kiwi.UnknownConstraint, lambda: solver.removeConstraint(ratio), 'Unknown constraint removal accepted')
    edits = kiwi.Solver(); z = kiwi.Variable('z'); edits.addConstraint(z >= 10)
    edits.addEditVariable(z, kiwi.strength.strong); edits.suggestValue(z, 5); edits.updateVariables()
    require(z.value() == 10, 'Required constraint lost to edit suggestion')
    edits.suggestValue(z, 20); edits.updateVariables(); require(z.value() == 20, 'Valid edit suggestion ignored')
    edits.removeEditVariable(z)
    raises(kiwi.UnknownEditVariable, lambda: edits.suggestValue(z, 30), 'Unknown edit variable accepted')
    return {'checks': ['linear-known-answer', 'duplicate-constraint', 'remove-and-replace', 'unsatisfiable-constraint', 'unknown-constraint', 'strength-priority', 'edit-suggestion', 'unknown-edit-variable']}

if __name__ == "__main__":
    raise SystemExit(main('kiwisolver', 'kiwisolver', functional))
