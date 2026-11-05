#!/usr/bin/env python3
"""Create the deterministic offline reference payload from verified local bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

COMMIT = "87f0227cb60147a26a1eeb4fb06e3b505e9c7261"
UPSTREAM_BASE = "https://github.com/llvm/llvm-project/blob/" + COMMIT + "/"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def records_for(source: dict, text: str) -> list[dict]:
    lines = text.splitlines()
    records = []
    upstream = source["upstream_path"]
    headings = []
    if upstream.endswith((".md", ".rst")):
        for i, line in enumerate(lines):
            m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
            if m:
                headings.append((i + 1, m.group(2), len(m.group(1))))
            elif i > 0 and re.fullmatch(r"([=~^\-])\1{2,}\s*", line) and lines[i - 1].strip():
                title = lines[i - 1].strip()
                if not re.fullmatch(r"[=~^\-]+", title):
                    headings.append((i, title, 1 if line.startswith("=") else 2))
        for j, (line, title, level) in enumerate(headings):
            end = headings[j + 1][0] - 1 if j + 1 < len(headings) else len(lines)
            records.append({"kind": "chapter", "title": title, "line": line, "end_line": end, "level": level})
        tokens = {}
        for i, line in enumerate(lines, 1):
            for pattern in (r"``([^`\n]{2,128})``", r"(?<!`)`([^`\n]{2,128})`(?!`)", r"(?<![\w-])(--?[A-Za-z][\w-]*(?:=[A-Za-z0-9_.-]+)?)"):
                for m in re.finditer(pattern, line):
                    value = m.group(1).strip()
                    if len(value) > 1 and not value.startswith(("http", "<")) and re.search(r"[A-Za-z]", value):
                        tokens.setdefault(value, i)
            m = re.match(r"^\.\. _([^:]+):\s*$", line)
            if m:
                tokens.setdefault(m.group(1), i)
        for token, line in sorted(tokens.items()):
            records.append({"kind": "literal_symbol", "title": token, "line": line, "end_line": line})
    if upstream.endswith(".td"):
        definitions = list(re.finditer(r"^\s*(def|class|multiclass|defm)\s+([A-Za-z_][\w]*)", text, re.M))
        for i, m in enumerate(definitions):
            line = text.count("\n", 0, m.start()) + 1
            end = text.count("\n", 0, definitions[i + 1].start()) if i + 1 < len(definitions) else len(lines)
            records.append({"kind": "tablegen_" + m.group(1), "title": m.group(2), "line": line, "end_line": max(line, end)})
        if upstream.endswith("/SparseTensorOps.td"):
            operations = list(re.finditer(r'^def\s+(\w+)\s*:\s*SparseTensor_Op\s*<\s*"([^"]+)"', text, re.M))
            for i, m in enumerate(operations):
                line = text.count("\n", 0, m.start()) + 1
                end = text.count("\n", 0, operations[i + 1].start()) if i + 1 < len(operations) else len(lines)
                records.append({"kind": "sparse_tensor_operation", "title": "sparse_tensor." + m.group(2),
                                "tablegen_definition": m.group(1), "line": line, "end_line": max(line, end)})
    elif upstream.endswith((".h", ".cpp")):
        symbols = {}
        for i, line in enumerate(lines, 1):
            for pattern in (r"\b(?:class|struct|enum class)\s+([A-Za-z_]\w*)", r"\b(LLVMRemark\w+)\b"):
                for m in re.finditer(pattern, line):
                    symbols.setdefault(m.group(1), i)
        for name, line in sorted(symbols.items()):
            records.append({"kind": "source_symbol_locator", "title": name, "line": line, "end_line": line})
    out = []
    for asset in source["asset_ids"]:
        for record in records:
            r = dict(record)
            key = f"{asset}\0{upstream}\0{r['kind']}\0{r['title']}\0{r['line']}"
            r.update({"entry_id": sha(key.encode())[:24], "asset_id": asset, "upstream_path": upstream,
                      "source_sha256": source["sha256"], "source_url": UPSTREAM_BASE + upstream + f"#L{r['line']}"})
            out.append(r)
    return out


def run(root: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("output must be a new directory")
    material_base = root if (root / "materials/source-manifest.json").is_file() else root / "payload"
    source_manifest = json.loads((material_base / "materials/source-manifest.json").read_text())
    assignments = json.loads((root / "assignments.json").read_text())
    if len(assignments) != 4 or {a["worker_id"] for a in assignments} != {"worker 011"}:
        raise ValueError("worker assignment mismatch")
    output.mkdir(parents=True)
    index = []
    copy_paths = {"materials/source-manifest.json", source_manifest["commit_evidence"]["path"], source_manifest["tag_evidence"]["path"]}
    copy_paths.update(x["path"] for x in source_manifest["tree_evidence"])
    for rec in source_manifest["files"]:
        p = material_base / rec["path"]
        b = p.read_bytes()
        if len(b) != rec["bytes"] or sha(b) != rec["sha256"]:
            raise ValueError("material source hash mismatch: " + rec["path"])
        copy_paths.add(rec["path"])
        index.extend(records_for(rec, b.decode()))
    for rel in sorted(copy_paths):
        out = output / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(material_base / rel, out)
        out.chmod(0o644)
    shutil.copyfile(root / "tools/reference_library.py", output / "reference_library.py")
    shutil.copyfile(root / "README.zh.md", output / "README.zh.md")
    shutil.copyfile(root / "LICENSE", output / "LICENSE")
    shutil.copyfile(root / "NOTICE", output / "NOTICE")
    index.sort(key=lambda x: (x["asset_id"], x["upstream_path"], x["line"], x["kind"], x["title"]))
    (output / "indexes").mkdir()
    (output / "indexes/entries.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in index))
    sparse = [x for x in index if x["kind"] == "sparse_tensor_operation"]
    if len(sparse) != 37 or len({x["title"] for x in sparse}) != 37:
        raise ValueError("incomplete fixed-version SparseTensor operation index")
    dump(output / "indexes/sparse-operations.json", sparse)
    scope_notes = {
        "reference.doc.openmp-opt": "Optimization overview, aware/unaware chapters, command-line options and all fixed-version OpenMP remark chapters. No OpenMP optimization or GPU offload was executed.",
        "reference.doc.llvm-remarks": "Remarks format, diagnostic options, llvm-remarkutil guide and same-commit C/C++ API source locators. No remark generation or parsing tool was executed.",
        "reference.doc.llvm-testsuite": "Complete fixed-version test-suite Guide source document. No test-suite programs, External inputs or official benchmark execution are included.",
        "reference.doc.mlir-sparse": "SparseTensorOps ODS sources, 37 operation locators, attribute/type/interface declarations and recursive literal include closure, plus verifier source and Passes.td. mlir-tblgen was not run; the index is not official generated HTML. No sparse program was compiled, lowered or executed.",
    }
    assets = []
    for a in assignments:
        asset_id = a["record_id"]
        sources = [f for f in source_manifest["files"] if asset_id in f["asset_ids"]]
        entries = [e for e in index if e["asset_id"] == asset_id]
        assets.append({
            "entity_id": asset_id, "record_id": asset_id, "entity_kind": "reference_asset",
            "name": a["resource_name"], "canonical_url": a["canonical_url"],
            "version": "20.1.8", "commit": COMMIT,
            "material_files": len(sources), "material_bytes": sum(s["bytes"] for s in sources),
            "chapter_entries": sum(e["kind"] == "chapter" for e in entries),
            "symbol_entries": sum(e["kind"] != "chapter" for e in entries),
            "scope": scope_notes[asset_id],
            "taxonomy_categories": a["taxonomy_categories"],
            "qualification": {"reference_material": True, "tool_functional": None, "dataset_verified": None, "official_benchmark": None},
        })
    dump(output / "assets.json", assets)
    summary = {"schema_version": 1, "commit": COMMIT, "assets": len(assets),
               "upstream_files": len(source_manifest["files"]), "upstream_bytes": sum(s["bytes"] for s in source_manifest["files"]),
               "index_entries": len(index), "chapter_entries": sum(e["kind"] == "chapter" for e in index),
               "symbol_entries": sum(e["kind"] != "chapter" for e in index), "sparse_operations": len(sparse),
               "tablegen_source_files": sum(s["path"].endswith(".td") for s in source_manifest["files"]),
               "tablegen_include_edges": len(source_manifest["tablegen_include_edges"]),
               "raw_source_modified": False, "upstream_doc_generator_executed": False}
    dump(output / "indexes/summary.json", summary)
    # Explicit payload inventory: no timestamps, no host paths, no self hash.
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            path.chmod(0o644)
            b = path.read_bytes()
            files.append({"path": path.relative_to(output).as_posix(), "bytes": len(b), "sha256": sha(b)})
    inventory = {"schema_version": 1, "commit": COMMIT, "files": files,
                 "allowed_manager_files": [".cpg-prefix.json"]}
    dump(output / "inventory.json", inventory)
    summary["inventory_sha256"] = sha((output / "inventory.json").read_bytes())
    summary["payload_files"] = len(files) + 1
    summary["payload_bytes"] = sum(x["bytes"] for x in files) + (output / "inventory.json").stat().st_size
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), args.output.absolute()), ensure_ascii=False, indent=2))
