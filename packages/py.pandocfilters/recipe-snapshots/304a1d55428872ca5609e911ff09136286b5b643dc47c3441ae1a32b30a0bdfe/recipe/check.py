#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Transform Pandoc JSON nodes while preserving source data and metadata.'
    import copy
    document = {"pandoc-api-version": [1, 22], "meta": {}, "blocks": [module.Para([module.Str("hello"), module.Space(), module.Str("compiler")])]}
    original = copy.deepcopy(document)
    def action(key, value, format, meta):
        if key == "Str":
            return module.Str(value.upper())
    result = module.walk(document, action, "html", {})
    require(module.stringify(result) == "HELLO COMPILER", "Node traversal/transformation failed")
    require(document == original, "Traversal unexpectedly modified the source document")
    require(result["pandoc-api-version"] == original["pandoc-api-version"] and result["meta"] == {}, "Metadata was lost")
    require(module.stringify(module.Str("雪")) == "雪", "Unicode leaf stringify failed")
    return {"checks": ["json-ast-transform", "source-preservation", "metadata-preservation", "unicode-stringify"]}

if __name__ == '__main__':
    raise SystemExit(main('pandocfilters', 'pandocfilters', functional))
