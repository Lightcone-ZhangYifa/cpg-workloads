"""A bounded, scope-aware LibCST function rename; no I/O or network access."""
from __future__ import annotations

import keyword
from dataclasses import dataclass

import libcst as cst
from libcst.metadata import GlobalScope, MetadataWrapper, PositionProvider, QualifiedName, QualifiedNameProvider, QualifiedNameSource, ScopeProvider


@dataclass(frozen=True)
class RenameResult:
    source: str
    changed_positions: tuple[tuple[int, int], ...]


def rename_function(source: str, old_name: str, new_name: str) -> RenameResult:
    """Rename one undecorated module function and its statically resolved names.

    This intentionally accepts a narrow contract: the old global binding must be
    unique; the new spelling must be absent from all identifier tokens. Identifier
    tokens must be ASCII. Global/nonlocal declarations and match statements are
    rejected because they need additional binding analysis. Attributes,
    comments, strings and locally shadowed names remain unchanged. Cross-module
    imports and reflective string lookups require a separate project-wide review.
    It is not a claim of whole-program equivalence for arbitrary Python programs.
    """
    for value in (old_name, new_name):
        if not isinstance(value, str) or not value.isascii() or not value.isidentifier() or keyword.iskeyword(value):
            raise ValueError("Names must be non-keyword ASCII Python identifiers")
    if old_name == new_name:
        raise ValueError("Old and new names must differ")
    wrapper = MetadataWrapper(cst.parse_module(source))
    class Contract(cst.CSTVisitor):
        def visit_Name(self, node):
            if not node.value.isascii():
                raise ValueError("Non-ASCII identifier tokens require Unicode normalization analysis")
            if node.value == new_name:
                raise ValueError("New identifier is already present; possible capture")

        def visit_Global(self, node):
            raise ValueError("Global declarations require additional binding analysis")

        def visit_Nonlocal(self, node):
            raise ValueError("Nonlocal declarations require additional binding analysis")

        def visit_Match(self, node):
            raise ValueError("Pattern matching requires additional capture-binding analysis")

    wrapper.module.visit(Contract())
    scopes = wrapper.resolve(ScopeProvider)
    names = wrapper.resolve(QualifiedNameProvider)
    positions = wrapper.resolve(PositionProvider)
    targets = [node for node in wrapper.module.body
               if isinstance(node, cst.FunctionDef) and node.name.value == old_name]
    if len(targets) != 1 or targets[0].decorators:
        raise ValueError("Exactly one undecorated top-level function is required")
    target = targets[0]
    global_scope = scopes[target.name]
    if not isinstance(global_scope, GlobalScope):
        raise ValueError("Target is not a module-level binding")
    assignments = list(global_scope[old_name])
    if len(assignments) != 1 or assignments[0].node is not target:
        raise ValueError("Rebound or ambiguous global function is unsupported")

    qualified_target = QualifiedName(old_name, QualifiedNameSource.LOCAL)
    changes: list[tuple[int, int]] = []

    class Rename(cst.CSTTransformer):
        def leave_Name(self, original_node, updated_node):
            if original_node.value != old_name:
                return updated_node
            qualified = names.get(original_node, set())
            qualified = qualified() if callable(qualified) else qualified
            if qualified == {qualified_target}:
                location = positions[original_node].start
                changes.append((location.line, location.column))
                return updated_node.with_changes(value=new_name)
            return updated_node

    transformed = wrapper.module.visit(Rename())
    if not changes:
        raise ValueError("No statically resolved target was found")
    return RenameResult(transformed.code, tuple(changes))
