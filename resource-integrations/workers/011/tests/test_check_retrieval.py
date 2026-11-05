"""Check the functional gate with real pinned text and incorrect reader results."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load("worker011_retrieval_check", ROOT / "cpg/recipe/check_retrieval.py")
reader = load("worker011_payload_reader", ROOT / "payload/reference_library.py")


class RetrievalQualification(unittest.TestCase):
    def setUp(self):
        self.prefix = ROOT / "payload"
        self.library = reader.ReferenceLibrary(
            self.prefix, expected_inventory_sha256=checker.INVENTORY_SHA256)

    def test_four_real_assets_search_and_read(self):
        result = checker.check_retrieval(self.library, self.prefix)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["assets_exercised"], 4)
        self.assertEqual(result["upstream_tool_executions"], 0)
        self.assertIsNone(result["upstream_functional_qualification"])

    def test_missing_search_evidence_fails(self):
        with mock.patch.object(self.library, "search", return_value=[]):
            with self.assertRaises(ValueError):
                checker.check_retrieval(self.library, self.prefix)

    def test_nonempty_but_incorrect_search_results_fail(self):
        real_search = self.library.search
        changes = (
            {"asset_ids": ["reference.doc.llvm-remarks"]},
            {"upstream_path": "incorrect/path"},
            {"line": 1},
            {"text": "incorrect source text"},
            {"source_sha256": "0" * 64},
            {"source_url": "https://github.com/llvm/llvm-project/blob/main/incorrect"},
        )
        for change in changes:
            with self.subTest(change=change):
                def altered(query, **kwargs):
                    hits = real_search(query, **kwargs)
                    if hits:
                        hits[0].update(change)
                    return hits
                with mock.patch.object(self.library, "search", side_effect=altered):
                    with self.assertRaises(ValueError):
                        checker.check_retrieval(self.library, self.prefix)

    def test_nonempty_but_incorrect_read_result_fails(self):
        with mock.patch.object(self.library, "read", return_value={"lines": ["wrong"]}):
            with self.assertRaises(ValueError):
                checker.check_retrieval(self.library, self.prefix)

    def test_false_match_for_absent_query_fails(self):
        real_search = self.library.search
        def false_positive(query, **kwargs):
            if query.startswith("CPG_WORKER011_QUERY_MUST_NOT_EXIST_"):
                return [{"unexpected": True}]
            return real_search(query, **kwargs)
        with mock.patch.object(self.library, "search", side_effect=false_positive):
            with self.assertRaises(ValueError):
                checker.check_retrieval(self.library, self.prefix)

    def test_accepted_path_traversal_fails(self):
        real_read = self.library.read
        def permissive(path, **kwargs):
            if path == "../LICENSE":
                return {"unexpected": True}
            return real_read(path, **kwargs)
        with mock.patch.object(self.library, "read", side_effect=permissive):
            with self.assertRaises(ValueError):
                checker.check_retrieval(self.library, self.prefix)


if __name__ == "__main__":
    unittest.main(verbosity=2)
