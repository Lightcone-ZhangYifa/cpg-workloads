"""Small library-first interface to the pinned native Tree-sitter C runtime.

Offsets and columns are UTF-8 byte offsets. The interface exposes syntax only:
an error-free tree does not prove semantic validity, name resolution, or typing.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path
from typing import Any


class Point(C.Structure):
    _fields_ = [("row", C.c_uint32), ("column", C.c_uint32)]


class Node(C.Structure):
    _fields_ = [("context", C.c_uint32 * 4), ("id", C.c_void_p), ("tree", C.c_void_p)]


class Edit(C.Structure):
    _fields_ = [("start_byte", C.c_uint32), ("old_end_byte", C.c_uint32), ("new_end_byte", C.c_uint32), ("start_point", Point), ("old_end_point", Point), ("new_end_point", Point)]


def point_at(source: bytes, offset: int) -> Point:
    if offset < 0 or offset > len(source):
        raise ValueError("offset outside source")
    prefix = source[:offset]
    prefix.decode("utf-8")  # Reject edits in the middle of an encoded code point.
    return Point(prefix.count(b"\n"), len(prefix.rsplit(b"\n", 1)[-1]))


class Parser:
    """An owned parser and current tree; use as a context manager or call close()."""
    def __init__(self, language: str, prefix: str | Path | None = None, *, runtime_prefix: str | Path | None = None, grammars_prefix: str | Path | None = None):
        if language not in ("c", "cpp", "rust"):
            raise ValueError("supported languages: c, cpp, rust")
        self.prefix = Path(prefix) if prefix else Path(__file__).resolve().parent / "install"
        self.runtime_prefix = Path(runtime_prefix) if runtime_prefix else self.prefix
        self.grammars_prefix = Path(grammars_prefix) if grammars_prefix else self.prefix
        self.lib = C.CDLL(str(self.runtime_prefix / "lib/libtree-sitter.so"))
        self.grammar = C.CDLL(str(self.grammars_prefix / ("lib/libtree-sitter-" + language + ".so")))
        signatures = {
            "ts_parser_new": (C.c_void_p, []), "ts_parser_delete": (None, [C.c_void_p]),
            "ts_parser_set_language": (C.c_bool, [C.c_void_p, C.c_void_p]),
            "ts_parser_parse_string": (C.c_void_p, [C.c_void_p, C.c_void_p, C.c_char_p, C.c_uint32]),
            "ts_tree_delete": (None, [C.c_void_p]), "ts_tree_edit": (None, [C.c_void_p, C.POINTER(Edit)]),
            "ts_tree_root_node": (Node, [C.c_void_p]), "ts_node_type": (C.c_char_p, [Node]),
            "ts_node_start_byte": (C.c_uint32, [Node]), "ts_node_end_byte": (C.c_uint32, [Node]),
            "ts_node_start_point": (Point, [Node]), "ts_node_end_point": (Point, [Node]),
            "ts_node_child_count": (C.c_uint32, [Node]), "ts_node_child": (Node, [Node, C.c_uint32]),
            "ts_node_is_named": (C.c_bool, [Node]), "ts_node_is_missing": (C.c_bool, [Node]),
            "ts_node_has_error": (C.c_bool, [Node]), "ts_node_is_error": (C.c_bool, [Node]),
            "ts_node_field_name_for_child": (C.c_char_p, [Node, C.c_uint32]),
            "ts_language_abi_version": (C.c_uint32, [C.c_void_p]),
        }
        for name, (restype, argtypes) in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = restype, argtypes
        getter = getattr(self.grammar, "tree_sitter_" + language)
        getter.restype, getter.argtypes = C.c_void_p, []
        self.language = getter()
        self.abi_version = self.lib.ts_language_abi_version(self.language)
        self.parser = self.lib.ts_parser_new()
        self.tree = None
        self.source = b""
        if not self.lib.ts_parser_set_language(self.parser, self.language):
            self.close()
            raise RuntimeError("runtime/grammar ABI mismatch")

    def __enter__(self) -> "Parser":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        if self.tree:
            self.lib.ts_tree_delete(self.tree)
            self.tree = None
        if self.parser:
            self.lib.ts_parser_delete(self.parser)
            self.parser = None

    def parse(self, source: str | bytes) -> dict[str, Any]:
        if not self.parser:
            raise RuntimeError("parser is closed")
        data = source.encode("utf-8") if isinstance(source, str) else bytes(source)
        data.decode("utf-8")
        if len(data) > 0xFFFFFFFF:
            raise ValueError("Tree-sitter byte offsets are uint32")
        tree = self.lib.ts_parser_parse_string(self.parser, None, data, len(data))
        if not tree:
            raise RuntimeError("parse returned null")
        if self.tree:
            self.lib.ts_tree_delete(self.tree)
        self.tree, self.source = tree, data
        return self.snapshot()

    def edit(self, start_byte: int, old_end_byte: int, replacement: str | bytes) -> dict[str, Any]:
        if not self.tree or not self.parser:
            raise RuntimeError("parse a document before editing")
        if not 0 <= start_byte <= old_end_byte <= len(self.source):
            raise ValueError("edit requires 0 <= start <= old_end <= source byte length")
        data = replacement.encode("utf-8") if isinstance(replacement, str) else bytes(replacement)
        data.decode("utf-8")
        old_source = self.source
        new_source = old_source[:start_byte] + data + old_source[old_end_byte:]
        if len(new_source) > 0xFFFFFFFF:
            raise ValueError("Tree-sitter byte offsets are uint32")
        edit = Edit(start_byte, old_end_byte, start_byte + len(data), point_at(old_source, start_byte), point_at(old_source, old_end_byte), point_at(new_source, start_byte + len(data)))
        self.lib.ts_tree_edit(self.tree, C.byref(edit))
        tree = self.lib.ts_parser_parse_string(self.parser, self.tree, new_source, len(new_source))
        if not tree:
            # An edited old tree cannot safely represent the old text after failure.
            self.lib.ts_tree_delete(self.tree)
            self.tree = None
            raise RuntimeError("incremental parse returned null; parse again from source")
        self.lib.ts_tree_delete(self.tree)
        self.tree, self.source = tree, new_source
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        if not self.tree:
            raise RuntimeError("no parsed tree")
        nodes = []
        # Native Tree-sitter can parse trees deeper than Python's call stack.
        # Push children right-to-left to retain the previous preorder, including
        # stable parent indexes and each child's field name, without recursion.
        pending = [(self.lib.ts_tree_root_node(self.tree), None, None)]
        while pending:
            node, parent, field = pending.pop()
            index = len(nodes)
            start, end = self.lib.ts_node_start_byte(node), self.lib.ts_node_end_byte(node)
            startp, endp = self.lib.ts_node_start_point(node), self.lib.ts_node_end_point(node)
            nodes.append({"index": index, "parent": parent, "field": field,
                "type": self.lib.ts_node_type(node).decode(), "named": bool(self.lib.ts_node_is_named(node)),
                "missing": bool(self.lib.ts_node_is_missing(node)), "error": bool(self.lib.ts_node_is_error(node)),
                "has_error": bool(self.lib.ts_node_has_error(node)), "start_byte": start, "end_byte": end,
                "start_point": [startp.row, startp.column], "end_point": [endp.row, endp.column]})
            for child_index in reversed(range(self.lib.ts_node_child_count(node))):
                raw = self.lib.ts_node_field_name_for_child(node, child_index)
                pending.append((self.lib.ts_node_child(node, child_index), index, raw.decode() if raw else None))
        return {"source_bytes": len(self.source), "abi_version": self.abi_version, "has_error": nodes[0]["has_error"], "nodes": nodes}
