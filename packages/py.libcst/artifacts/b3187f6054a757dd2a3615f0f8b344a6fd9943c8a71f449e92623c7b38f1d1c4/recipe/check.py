#!/usr/bin/env python3
"""Installed functional check for LibCST with syntax-preserving transformations."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(cst, work):
    """Parse, preserve layout, rename, resolve positions and execute transformed code."""
    source = "# preserve this comment\nvalue = 2  # number\nresult = value + 5\nprint(result)\n"
    module = cst.parse_module(source)
    require(module.code == source, "Concrete syntax round trip changed formatting")
    class Rename(cst.CSTTransformer):
        def leave_Name(self, original_node, updated_node):
            return updated_node.with_changes(value="operand") if original_node.value == "value" else updated_node
    rewritten = module.visit(Rename())
    require(rewritten.code == source.replace("value", "operand"), "Rename changed unrelated syntax")
    metadata = installed_module("libcst.metadata")
    wrapper = metadata.MetadataWrapper(module)
    positions = wrapper.resolve(metadata.PositionProvider)
    locations = sorted((p.start.line, p.start.column) for n, p in positions.items()
                       if isinstance(n, cst.Name) and n.value == "value")
    require(locations == [(2, 0), (3, 9)], f"Wrong identifier positions: {locations}")
    for name, code in [("original.py", module.code), ("rewritten.py", rewritten.code)]:
        path = work / name; path.write_text(code)
        require(child([sys.executable, "-I", path]).stdout == "7\n", "Transformation changed execution")
    require(rewritten.deep_equals(cst.parse_module(rewritten.code)), "Transformed CST did not round trip")
    raises(cst.ParserSyntaxError, lambda: cst.parse_module("def broken(:\n pass\n"), "Invalid Python accepted")
    raises(cst.CSTValidationError, lambda: cst.Name("not-a-name"), "Invalid identifier accepted")
    return {"checks": ["lossless-source-roundtrip", "identifier-transform", "position-metadata",
                       "original-and-transformed-execution", "cst-roundtrip", "syntax-error", "invalid-identifier"],
            "identifier_locations": locations}

if __name__ == "__main__":
    raise SystemExit(main("libcst", "libcst", functional))
