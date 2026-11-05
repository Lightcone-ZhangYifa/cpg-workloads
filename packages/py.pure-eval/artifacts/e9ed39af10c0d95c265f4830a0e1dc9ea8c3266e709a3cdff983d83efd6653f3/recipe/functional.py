import ast
from pure_eval import Evaluator,CannotEval
e=Evaluator({'x':7})
assert e[ast.parse('x * 6',mode='eval').body] == 42
try: e[ast.parse('dangerous()',mode='eval').body]
except CannotEval: pass
else: raise AssertionError('unsafe call unexpectedly evaluated')
print('CPG_FUNCTIONAL_OK:pure-eval:ast-and-negative')
