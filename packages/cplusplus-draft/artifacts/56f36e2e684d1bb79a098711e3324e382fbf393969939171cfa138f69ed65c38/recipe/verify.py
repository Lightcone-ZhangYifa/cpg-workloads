"""Read-only, stdlib-only verification of one installed reference_corpus payload."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

sys.dont_write_bytecode = True


def verify(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root / "payload-manifest.json").read_text())
    entries = manifest["files"]
    expected = {r["path"] for r in entries}
    if len(expected) != len(entries): raise ValueError("duplicate manifest paths")
    # The original CPG manager adds only this root-level owner receipt.
    manager_files = {"payload-manifest.json", ".cpg-prefix.json"}
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if p.is_file() and p.relative_to(root).as_posix() not in manager_files}
    if actual != expected:
        raise ValueError(f"payload set mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    checked = []
    for row in entries:
        path = root / row["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("unsafe payload member: " + row["path"])
        data = path.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("payload hash mismatch: " + row["path"])
        checked.append(row["path"])
    spec = importlib.util.spec_from_file_location("reference_corpus_reader", root / "reader.py")
    reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
    corpus = reader.Corpus(root)
    resource = corpus.metadata["resource_id"]
    results = []
    def ok(name: str, condition) -> None:
        if not condition: raise ValueError("acceptance failed: " + name)
        results.append({"name": name, "status": "passed"})
    uri = (root / "search.sqlite").as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as con:
        ok("sqlite_integrity", con.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
        count = con.execute("SELECT count(*) FROM fts").fetchone()[0]
        ok("complete_index_row_count", count == json.loads((root / "index-stats.json").read_text())["sections"])
    anchors = json.loads((root / "anchors.json").read_text())
    ok("anchor_paths_are_pinned", all(a["path"] in corpus.files for a in anchors))
    ok("anchor_line_bounds", all(isinstance(a["line_start"], int) and a["line_start"] >= 1
                                 and a["line_end"] >= a["line_start"] for a in anchors))
    for query in ("", "   ", "!@#$", "x"*513):
        try: corpus.search(query)
        except ValueError: pass
        else: raise ValueError("invalid query accepted")
    ok("invalid_queries_rejected", True)
    for limit in (0, 101, -1, True, 1.5):
        try: corpus.search("compiler", limit)
        except ValueError: pass
        else: raise ValueError("invalid limit accepted")
    ok("invalid_limits_rejected", True)
    ok("query_operators_are_literal", corpus.search('nonexistent_cpg_reference OR 1=1') == [])
    try: corpus.read_source("../metadata.json")
    except (KeyError, ValueError): pass
    else: raise ValueError("unregistered path accepted")
    ok("unregistered_path_rejected", True)
    if resource == "arm-acle":
        ok("no_closed_legacy_release", not any("legacyreleases" in p for p in expected))
        for name in ("vaddq_s32", "vld1q_u8", "vaddq_s16"):
            found = corpus.intrinsic(name)
            ok("intrinsic_" + name, bool(found))
            for row in found:
                line = corpus.read_source(row["path"], row["line"], row["line"])["text"]
                ok("intrinsic_source_" + name + "_" + row["path"], name in line)
        for query in ("__ARM_FEATURE_SVE", "streaming", "MVE"):
            ok("fulltext_" + query, bool(corpus.search(query)))
        ok("examples_preserved", (root / "examples.jsonl").stat().st_size > 1000)
        ok("open_spec_licenses", all((root / "upstream" / n / "LICENSE.md").is_file()
                                    for n in ("main", "morello", "mve_intrinsics", "neon_intrinsics")))
    elif resource == "rustc-dev-guide":
        for query in ("MIR", "HIR", "incremental", "query", "compiletest"):
            found = corpus.search(query)
            ok("fulltext_" + query, bool(found))
            row = found[0]; text = corpus.read_source(row["path"], row["line_start"], row["line_end"])["text"]
            ok("source_identity_" + query, bool(text))
        stats = json.loads((root / "build-statistics.json").read_text())
        ok("mdbook_includes_resolved", stats["resolved_includes"] == 2)
        ok("compiler_paths_recorded", stats["compiler_path_references"] > 100)
        ok("upstream_dual_license_retained", all((root / "upstream" / x).is_file() for x in ("LICENSE-MIT", "LICENSE-APACHE")))
    elif resource == "cplusplus-draft":
        for name in ("basic.life", "basic.lval", "intro.object", "expr.add", "intro.races"):
            ok("anchor_" + name, len(corpus.anchor(name)) == 1)
            ok("search_" + name, bool(corpus.search(name)))
        ok("working_draft_identity", corpus.metadata["version"] == "N5054")
        ok("restricted_body_not_distributed", not any(p.endswith(".tex") for p in expected))
        try: corpus.read_source(corpus.anchor("basic.life")[0]["path"])
        except FileNotFoundError: pass
        else: raise ValueError("C++ absent body misrepresented")
        ok("absent_body_explicit", True)
    elif resource == "wg14-public-docs":
        rows = json.loads((root / "documents.json").read_text())
        ok("bounded_selection", len(rows) == 10)
        ok("all_downloads_pinned", all(len(r["sha256"]) == 64 and r["bytes"] > 0 for r in rows))
        ok("public_does_not_imply_redistributable", all(r["redistributed"] is False for r in rows))
        ok("no_restricted_body", not any(p.endswith((".pdf", ".htm")) for p in expected))
        for query in ("N1256", "N1570", "N3096", "DR451", "DR481"):
            ok("metadata_search_" + query, bool(corpus.search(query)))
    else: raise ValueError("unknown corpus")
    if (root / "render-manifest.json").exists():
        rendered = json.loads((root / "render-manifest.json").read_text())
        ok("all_rendered_pages_exist", all((root / p["html"]).is_file() for p in rendered))
        ok("all_source_pages_exist", all((root / "source" / (p["source"] + ".html")).is_file() for p in rendered))
    return {"resource_id": resource, "status": "passed", "payload_files_verified": len(checked),
            "index_rows": count, "checks": results, "check_count": len(results),
            "evidence_scope": corpus.metadata["scope"], "network_required": False,
            "compiler_semantics_or_hardware_verified": False}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    try: result = verify(args.root)
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False)); raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
