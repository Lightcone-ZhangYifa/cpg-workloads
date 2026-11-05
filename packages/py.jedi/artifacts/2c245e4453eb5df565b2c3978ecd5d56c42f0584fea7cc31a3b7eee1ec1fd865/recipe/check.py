#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(jedi, work):
    """Check local completion, definitions, inference and call signatures."""
    completion_source = "text = 'compiler'\ntext.st"
    script = jedi.Script(completion_source, path=str(work / 'completion.py'))
    names = {item.name for item in script.complete(2, len('text.st'))}
    require({'startswith', 'strip'} <= names, 'String completion missing expected members')
    source = 'def square(x):\n    return x * x\nanswer = square(7)\n'
    analysis = jedi.Script(source, path=str(work / 'module.py'))
    definitions = analysis.goto(3, 12)
    require(len(definitions) == 1 and definitions[0].name == 'square' and definitions[0].line == 1, 'Go-to-definition mismatch')
    inferred = analysis.infer(3, 2)
    require(any(item.name == 'int' for item in inferred), 'Return type inference failed')
    signatures = analysis.get_signatures(3, 16)
    require(len(signatures) == 1 and [p.name for p in signatures[0].params] == ['x'], 'Signature inference failed')
    references = analysis.get_references(1, 5)
    require(len(references) == 2 and all(item.name == 'square' for item in references), 'Reference lookup mismatch')
    raises(ValueError, lambda: analysis.complete(0, 0), 'Invalid source position accepted')
    return {'checks': ['local-attribute-completion', 'go-to-definition', 'integer-inference', 'call-signature', 'references', 'invalid-position'], 'scope': 'local static Python analysis; remote environments and editor integrations not exercised'}

if __name__ == "__main__":
    raise SystemExit(main('jedi', 'jedi', functional))
