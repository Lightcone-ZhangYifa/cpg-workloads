#!/usr/bin/env python3
"""Network-enabled preparation only; never imported by the offline reader.

Material bytes are fixed to a public LLVM commit. Raw GitHub downloads are
independently checked against Git blob identities from LLVM's Gitiles mirror.
Only the documented scope is collected; this is not a full LLVM checkout.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import posixpath
import re
import time
import urllib.request
from pathlib import Path, PurePosixPath

COMMIT = "87f0227cb60147a26a1eeb4fb06e3b505e9c7261"
TAG = "llvmorg-20.1.8"
RAW = f"https://raw.githubusercontent.com/llvm/llvm-project/{COMMIT}/"
GITILES = f"https://llvm.googlesource.com/llvm-project/+/{COMMIT}"
LICENSES = ["LICENSE.TXT", "llvm/LICENSE.TXT", "mlir/LICENSE.TXT", "openmp/LICENSE.TXT"]
SPARSE = "mlir/include/mlir/Dialect/SparseTensor/IR/SparseTensorOps.td"
SCOPES = {
    "reference.doc.openmp-opt": [
        "openmp/docs/optimizations/Overview.rst",
        "openmp/docs/optimizations/OpenMPOpt.rst",
        "openmp/docs/optimizations/OpenMPUnawareOptimizations.rst",
        "openmp/docs/CommandLineArgumentReference.rst",
    ],
    "reference.doc.llvm-remarks": [
        "llvm/docs/Remarks.rst", "llvm/docs/CommandGuide/llvm-remarkutil.rst",
        "llvm/include/llvm/Remarks/Remark.h", "llvm/include/llvm/Remarks/RemarkParser.h",
        "llvm/include/llvm-c/Remarks.h",
    ],
    "reference.doc.llvm-testsuite": ["llvm/docs/TestSuiteGuide.md"],
    "reference.doc.mlir-sparse": [
        SPARSE, "mlir/include/mlir/Dialect/SparseTensor/IR/CMakeLists.txt",
        "mlir/include/mlir/Dialect/SparseTensor/Transforms/Passes.td",
        "mlir/lib/Dialect/SparseTensor/IR/SparseTensorDialect.cpp",
    ],
}


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def blob(b: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CPG-reference-material-preparation/1"})
    last = None
    for delay in (0, 0.5, 1.5):
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read()
        except Exception as e:
            last = e
    raise RuntimeError(f"failed to retrieve {url}: {last}")


def tree_sha(entries: list[dict]) -> str:
    payload = bytearray()
    for ent in sorted(entries, key=lambda x: (x["name"] + ("/" if x["type"] == "tree" else "")).encode()):
        mode = format(ent["mode"], "o")
        payload.extend(mode.encode() + b" " + ent["name"].encode() + b"\0" + bytes.fromhex(ent["id"]))
    return hashlib.sha1(b"tree " + str(len(payload)).encode() + b"\0" + payload).hexdigest()


def safe_relative(path: str) -> str:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or "\\" in path or str(p) != path:
        raise ValueError(f"unsafe path: {path}")
    return path


def run(root: Path) -> dict:
    source_root = root / "materials" / "upstream"
    evidence_root = root / "evidence" / "upstream"
    source_root.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    commit_bytes = get(GITILES + "?format=JSON")
    commit = json.loads(commit_bytes.decode()[4:])
    if commit["commit"] != COMMIT:
        raise ValueError("upstream commit identity mismatch")
    (evidence_root / "commit.gitiles.json").write_bytes(commit_bytes)
    tag_url = f"https://llvm.googlesource.com/llvm-project/+/refs/tags/{TAG}?format=JSON"
    tag_bytes = get(tag_url)
    tag_commit = json.loads(tag_bytes.decode()[4:])
    if tag_commit["commit"] != COMMIT:
        raise ValueError("release tag no longer resolves to the fixed commit")
    (evidence_root / "tag.gitiles.json").write_bytes(tag_bytes)
    trees: dict[str, dict] = {}
    tree_evidence: list[dict] = []

    def directory(path: str) -> dict:
        if path not in trees:
            url = GITILES + ("/" + path if path else "") + "/?format=JSON"
            b = get(url)
            d = json.loads(b.decode()[4:])
            computed = tree_sha(d["entries"])
            if computed != d["id"]:
                raise ValueError(f"Git tree object mismatch: {path}")
            if not path and d["id"] != commit["tree"]:
                raise ValueError("commit root tree mismatch")
            if path:
                parent, name = posixpath.split(path)
                parent_entries = directory(parent)["entries"]
                expected = next((x for x in parent_entries if x["name"] == name), None)
                if expected is None or expected["type"] != "tree" or expected["id"] != d["id"]:
                    raise ValueError(f"tree ancestry mismatch: {path}")
            file_name = (path.replace("/", "__") or "root") + ".gitiles.json"
            output = evidence_root / file_name
            output.write_bytes(b)
            tree_evidence.append({"upstream_path": path, "path": output.relative_to(root).as_posix(),
                                  "sha256": digest(b), "tree_sha1": d["id"], "url": url})
            trees[path] = d
        return trees[path]

    # The complete documented OpenMP optimization/remark chapter sets are small.
    scopes = {k: set(v) for k, v in SCOPES.items()}
    for subdir in ("openmp/docs/optimizations", "openmp/docs/remarks"):
        for ent in directory(subdir)["entries"]:
            if ent["type"] == "blob" and ent["name"].endswith((".rst", ".md")):
                scopes["reference.doc.openmp-opt"].add(subdir + "/" + ent["name"])

    records: dict[str, dict] = {}

    def fetch(path: str) -> dict:
        safe_relative(path)
        parent, name = posixpath.split(path)
        ent = next((e for e in directory(parent)["entries"] if e["name"] == name), None)
        if ent is None or ent["type"] != "blob" or ent["mode"] != 0o100644:
            raise ValueError(f"expected ordinary upstream source file: {path}")
        b = get(RAW + path)
        if blob(b) != ent["id"]:
            raise ValueError(f"Git blob mismatch between official mirrors: {path}")
        out = source_root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.is_symlink():
            raise ValueError(f"refuse source symlink: {out}")
        out.write_bytes(b)
        out.chmod(0o644)
        return {"upstream_path": path, "path": out.relative_to(root).as_posix(),
                "sha256": digest(b), "bytes": len(b), "git_blob_sha1": ent["id"],
                "url": RAW + path, "git_url": f"https://github.com/llvm/llvm-project/blob/{COMMIT}/{path}",
                "mode": "0644"}

    pending = set(LICENSES)
    for paths in scopes.values():
        pending.update(paths)
    # Directory lookups remain sequential and cached. Raw-file transfers within
    # a round can be parallel after the directory identities are established.
    include_edges: list[dict] = []
    while pending:
        current = sorted(pending - set(records))
        pending.clear()
        for p in current:
            directory(posixpath.dirname(p))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for rec in pool.map(fetch, current):
                records[rec["upstream_path"]] = rec
        for p in current:
            if not p.endswith(".td"):
                continue
            text = (source_root / p).read_text()
            for lineno, line in enumerate(text.splitlines(), 1):
                m = re.match(r'^\s*include\s+"([^"\n]+)"', line)
                if not m:
                    continue
                inc = safe_relative(m.group(1))
                if inc.startswith("mlir/"):
                    target = "mlir/include/" + inc
                elif inc.startswith("llvm/"):
                    target = "llvm/include/" + inc
                else:
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(p), inc))
                safe_relative(target)
                include_edges.append({"from": p, "line": lineno, "include": inc, "to": target})
                scopes["reference.doc.mlir-sparse"].add(target)
                if target not in records:
                    pending.add(target)

    for rec in records.values():
        rec["asset_ids"] = sorted(k for k, v in scopes.items() if rec["upstream_path"] in v)
        rec["role"] = "license" if rec["upstream_path"] in LICENSES else "upstream_reference"
    manifest = {
        "schema_version": 1, "worker_id": "worker 011", "upstream": "llvm/llvm-project",
        "tag": TAG, "commit": COMMIT, "root_tree_sha1": commit["tree"],
        "license": "Apache-2.0 WITH LLVM-exception; retained project notices and historical terms",
        "commit_evidence": {"path": "evidence/upstream/commit.gitiles.json", "sha256": digest(commit_bytes), "url": GITILES + "?format=JSON"},
        "tag_evidence": {"path": "evidence/upstream/tag.gitiles.json", "sha256": digest(tag_bytes), "url": tag_url},
        "files": [records[p] for p in sorted(records)],
        "tree_evidence": sorted(tree_evidence, key=lambda x: x["upstream_path"]),
        "tablegen_include_edges": sorted(include_edges, key=lambda x: (x["from"], x["line"])),
        "scope": {k: sorted(v) for k, v in scopes.items()},
        "qualification": {"reference_material_only": True, "tool_functional": None, "official_benchmark": None, "hardware": None},
        "limits": [
            "Source snapshots, not a full LLVM source checkout or installed toolchain.",
            "SparseTensor documentation is represented by exact ODS source and its recursive literal include closure.",
            "Upstream source references outside this explicit set remain external; no complete C++ build closure is claimed.",
            "Network is used only by this explicit preparation command; offline reader and verification never fetch missing content.",
        ],
    }
    (root / "materials" / "source-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"files": len(records), "bytes": sum(r["bytes"] for r in records.values()), "trees": len(tree_evidence), "include_edges": len(include_edges)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve()), indent=2))
