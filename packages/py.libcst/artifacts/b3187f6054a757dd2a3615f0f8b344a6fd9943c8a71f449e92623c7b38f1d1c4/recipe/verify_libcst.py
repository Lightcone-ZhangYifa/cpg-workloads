#!/usr/bin/env python3
"""Execute the scoped codemod contract with installed LibCST 1.9.0, offline."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import libcst as cst
from cpg_libcst import rename_function


def verify(output: Path) -> dict:
    if importlib.metadata.version("libcst") != "1.9.0":
        raise RuntimeError("This inherited profile requires LibCST 1.9.0")
    output.mkdir(parents=True, exist_ok=False)
    source = (Path(__file__).resolve().parent / "fixtures/scoped.py").read_text()
    result = rename_function(source, "target", "optimized_target")
    # Independent expected edit spans, not a broad text replacement.
    expected_lines = source.splitlines(keepends=True)
    expected_spans = [(5, 4), (12, 15), (26, 8), (29, 22)]
    for line, column in expected_spans:
        assert expected_lines[line-1][column:column+6] == "target", (line, column)
        expected_lines[line-1] = expected_lines[line-1][:column] + "optimized_target" + expected_lines[line-1][column+6:]
    if result.source != "".join(expected_lines):
        raise AssertionError("Transformation changed unexpected bytes or missed a binding")
    if set(result.changed_positions) != set(expected_spans):
        raise AssertionError("Qualified-name edits differ from the independent location oracle")
    if cst.parse_module(source).code != source or cst.parse_module(result.source).code != result.source:
        raise AssertionError("Concrete syntax round-trip changed bytes")
    outputs = []
    for name, contents in (("original.py", source), ("rewritten.py", result.source)):
        path = output / name
        path.write_text(contents)
        compile(contents, name, "exec")
        run = subprocess.run([sys.executable, "-B", "-I", str(path)], capture_output=True, text=True,
                             timeout=20, check=True)
        (output / (name + ".stdout")).write_text(run.stdout)
        (output / (name + ".stderr")).write_text(run.stderr)
        outputs.append(run.stdout)
    if outputs[0] != outputs[1]:
        raise AssertionError("Original and transformed fixture differ at runtime")
    if json.loads(outputs[1].splitlines()[0]) != [3 * (i * i + 3) for i in range(-8, 9)]:
        raise AssertionError("Independent runtime result oracle failed")
    if outputs[1].splitlines()[1] != "15 3 target 17":
        raise AssertionError("Shadowed call, attribute, literal or suffix changed")
    negative_cases = {
        "missing-target": ("def other():\n    return 1\n", "target", "fresh"),
        "duplicate-target": ("def target(): pass\ndef target(): pass\n", "target", "fresh"),
        "reassigned-global": ("def target(): pass\ntarget = 7\n", "target", "fresh"),
        "global-name-collision": ("def target(): pass\nfresh = 1\n", "target", "fresh"),
        "nested-capture": ("def target(): pass\ndef outer(fresh): return target()\n", "target", "fresh"),
        "invalid-new-name": (source, "target", "bad-name"),
        "keyword-new-name": (source, "target", "class"),
        "same-name": (source, "target", "target"),
        "decorated-target": ("@wrap\ndef target(): pass\n", "target", "fresh"),
        "global-deletion": ("def target(): return 1\ndef remove():\n    global target\n    del target\nremove()\n", "target", "fresh"),
        "unicode-new-name-normalization": ("def target(): return 1\nK = 9\nassert target() == 1\n", "target", "\u212a"),
        "unicode-old-name-alias": ("def target(): return 1\nassert \uff54\uff41\uff52\uff47\uff45\uff54() == 1\n", "target", "fresh"),
        "pattern-capture-shadow": ("def target(): return 1\ndef local(value):\n    match value:\n        case target: return target\n", "target", "fresh"),
        "nonlocal-declaration": ("def target(): return 1\ndef outer():\n    x = 1\n    def inner():\n        nonlocal x\n        return target() + x\n", "target", "fresh"),
    }
    rejected = {}
    for name, args in negative_cases.items():
        try:
            rename_function(*args)
        except ValueError as error:
            rejected[name] = str(error)
        else:
            raise AssertionError("Unsafe contract was accepted: " + name)
    try:
        rename_function("def broken(:\n pass\n", "target", "fresh")
    except cst.ParserSyntaxError:
        rejected["syntax-error"] = "ParserSyntaxError"
    else:
        raise AssertionError("Invalid syntax accepted")
    patch = "".join(difflib.unified_diff(source.splitlines(keepends=True), result.source.splitlines(keepends=True),
                                         fromfile="a/scoped.py", tofile="b/scoped.py"))
    (output / "rename.patch").write_text(patch)
    report = {"schema_version": 1, "record_id": "review.engineering.libcst", "entity_id": "py.libcst",
              "status": "passed", "version": importlib.metadata.version("libcst"),
              "pyyaml_version": importlib.metadata.version("PyYAML"), "python": sys.version.split()[0],
              "stage": "offline-functional-validation", "network_required": False,
              "checks": ["lossless-roundtrip", "qualified-name-metadata", "independent-exact-edit-spans",
                         "comment-whitespace-preservation", "literal-preservation", "local-shadow-preservation",
                         "attribute-preservation", "closure-reference-rename", "alias-reference-rename",
                         "recompile-both-programs", "equivalent-fixture-execution", "independent-runtime-oracle"],
              "changed_positions": result.changed_positions, "negative_cases": rejected,
              "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "rewritten_sha256": hashlib.sha256(result.source.encode()).hexdigest(),
              "scope": "One undecorated, unambiguous top-level Python function; ASCII identifiers and direct static references in one module; no global/nonlocal declarations or match statements.",
              "limitations": ["No cross-module import rewrite", "No dynamic reflection/string-lookup equivalence claim",
                              "A conservative new-name collision guard rejects any existing identifier token",
                              "Non-ASCII identifiers, global/nonlocal declarations and match statements are rejected"]}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    print(json.dumps(verify(opts.output.resolve()), indent=2))
