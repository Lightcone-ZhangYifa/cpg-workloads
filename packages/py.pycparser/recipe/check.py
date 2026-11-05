#!/usr/bin/env python3
"""Installed functional check for the preprocessed-C parser and generator."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require

def functional(pycparser, work):
    """Check C AST structure, visitor traversal, generation and syntax rejection."""
    ast = installed_module("pycparser.c_ast")
    generator = installed_module("pycparser.c_generator")
    source = """typedef unsigned long usize;
struct Pair { int left; int right; };
int sum(const int *values, usize n) {
  int total = 0;
  for (usize i = 0; i < n; ++i) { total += values[i]; }
  return total;
}
"""
    parser = pycparser.CParser()
    tree = parser.parse(source, filename="fixture.c")
    class Inventory(ast.NodeVisitor):
        def __init__(self): self.functions = []; self.loops = 0; self.refs = 0; self.typedefs = []
        def visit_FuncDef(self, node): self.functions.append(node.decl.name); self.generic_visit(node)
        def visit_For(self, node): self.loops += 1; self.generic_visit(node)
        def visit_ArrayRef(self, node): self.refs += 1; self.generic_visit(node)
        def visit_Typedef(self, node): self.typedefs.append(node.name); self.generic_visit(node)
        def snapshot(self): return [self.functions, self.loops, self.refs, self.typedefs]
    before = Inventory(); before.visit(tree)
    require(before.snapshot() == [["sum"], 1, 1, ["usize"]], "C visitor produced wrong structure")
    require(tree.ext[-1].coord.file == "fixture.c" and tree.ext[-1].coord.line == 3, "C source location lost")
    emitted = generator.CGenerator().visit(tree)
    after = Inventory(); after.visit(parser.parse(emitted, filename="regenerated.c"))
    require(after.snapshot() == before.snapshot(), "C generator changed AST structure")
    target = work / "regenerated.c"; target.write_text(emitted)
    require(target.read_text() == emitted and "const int *values" in emitted, "Generated source changed pointer declaration")
    raises(pycparser.c_parser.ParseError, lambda: parser.parse("int broken( { return 0; }"), "Malformed C accepted")
    raises(pycparser.c_parser.ParseError, lambda: parser.parse("int f(void) { return @; }"), "Illegal C token accepted")
    return {"checks": ["typedef-struct-loop-array-ast", "visitor-traversal", "source-location",
                       "c-generation-and-reparse", "generated-file-roundtrip", "malformed-declaration", "illegal-token"],
            "scope": "preprocessed C parsing and generation; no preprocessing or compiler qualification"}

if __name__ == "__main__":
    raise SystemExit(main("pycparser", "pycparser", functional))
