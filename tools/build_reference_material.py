#!/usr/bin/env python3
"""Build one reference resource's local payload and call the official CPG pack API."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

from compiler_playground.packages import pack, verify_package

TOOLS = Path(__file__).resolve().parent


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def safe_relative(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or path.as_posix() != name:
        raise ValueError("Noncanonical source-relative path")
    return name


def source_bytes(package: Path, name: str) -> bytes:
    path = package / safe_relative(name)
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError("Reference build inputs must be ordinary files")
    return path.read_bytes()


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o644)


def index_source(source: dict, raw: bytes, resource: dict) -> list[dict]:
    upstream = source["upstream_path"]
    suffix = Path(upstream).suffix.lower()
    if source["role"] != "reference" or suffix not in {".md", ".rst", ".td", ".h", ".hpp", ".cpp", ".c", ".txt"}:
        return []
    text = raw.decode("utf-8"); lines = text.splitlines(); entries = []
    def add(kind, title, line, end=None, **extra):
        row = {"entity_id": resource["id"], "version": resource["version"], "commit": resource["commit"],
               "upstream_path": upstream, "source_sha256": source["sha256"], "kind": kind, "title": title,
               "line": line, "end_line": end or line, "text": lines[line - 1], **extra}
        row["entry_id"] = sha(encoded(row))[:24]
        entries.append(row)
    if suffix in {".rst", ".md"}:
        headings = []
        fenced = False
        for offset, line in enumerate(lines):
            if line.lstrip().startswith("```"):
                fenced = not fenced
            match = re.match(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", line) if not fenced else None
            if suffix == ".md" and match:
                headings.append((offset + 1, match[2]))
            elif suffix == ".rst" and offset and re.fullmatch(r"([=~^\-`:#*+])\1{2,}", line.strip()):
                title = lines[offset - 1].strip()
                if title and not re.fullmatch(r"([=~^\-`:#*+])\1{2,}", title):
                    headings.append((offset, title))
        for index, (line, title) in enumerate(headings):
            add("chapter", title, line, headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines))
    for number, line in enumerate(lines, 1):
        tokens = set()
        for match in re.finditer(r"``([^`\n]+)``|(?<!`)`([^`\n]+)`(?!`)", line):
            token = match[1] or match[2]
            if 1 < len(token) <= 128 and not token.startswith(("http", "<")):
                tokens.add(token)
        for match in re.finditer(r"(?<![\w-])(?:llvm\.loop\.[\w.]+|--?[A-Za-z][\w-]*(?:=[\w.-]+)?)", line):
            tokens.add(match[0])
        for token in sorted(tokens):
            add("literal_symbol", token, number)
        if suffix in {".h", ".hpp", ".cpp", ".c"}:
            for match in re.finditer(r"\b(?:class|struct|enum class)[ \t]+([A-Za-z_]\w*)|\b(LLVMRemark\w+)\b", line):
                add("declaration", match[1] or match[2], number)
    if suffix == ".td":
        definitions = list(re.finditer(r"^[ \t]*(def|class|multiclass|defm)[ \t]+([A-Za-z_]\w*)", text, re.M))
        for index, match in enumerate(definitions):
            line = text.count("\n", 0, match.start()) + 1
            end = text.count("\n", 0, definitions[index + 1].start()) if index + 1 < len(definitions) else len(lines)
            add("tablegen_definition", match[2], line, max(line, end))
        for match in re.finditer(r'^[ \t]*def[ \t]+(\w+)\s*:\s*(?:Interface)?Pass\s*<\s*"([^"]+)"', text, re.M):
            line = text.count("\n", 0, match.start()) + 1
            following = next((item for item in definitions if item.start() > match.start()), None)
            end = text.count("\n", 0, following.start()) if following else len(lines)
            add("pass", match[1], line, max(line, end), pass_argument=match[2], not_a_runtime_registration_claim=True)
        for match in re.finditer(r'^[ \t]*def[ \t]+(\w+)\s*:\s*SparseTensor_Op\s*<\s*"([^"]+)"', text, re.M):
            line = text.count("\n", 0, match.start()) + 1
            following = next((item for item in definitions if item.start() > match.start()), None)
            end = text.count("\n", 0, following.start()) if following else len(lines)
            add("operation", "sparse_tensor." + match[2], line, max(line, end),
                tablegen_definition=match[1], not_a_runtime_registration_claim=True)
    return list({row["entry_id"]: row for row in entries}.values())


def build_payload(package: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Use a new payload directory")
    package = package.resolve()
    reference = read_json(package / "reference.json")
    lock = read_json(package / "source-lock.json")
    if (lock["resource_id"], lock["version"], lock["commit"]) != (reference["id"], reference["version"], reference["commit"]):
        raise ValueError("Reference and source lock identities differ")
    output.mkdir(parents=True)
    resource = {key: reference[key] for key in ("id", "name", "version", "commit", "primary_path", "canonical_url", "software", "scope")}
    if "generated_includes" in reference:
        resource["generated_includes"] = reference["generated_includes"]
    resource["entity_kind"] = "reference_asset"
    resource["qualification"] = {"upstream_tool_functional": None, "official_benchmark": None, "dataset_verified": None}
    entries, paths = [], set()
    for source in lock["files"]:
        name = safe_relative(source["path"])
        if name in paths or name != "materials/" + safe_relative(source["upstream_path"]):
            raise ValueError("Duplicate or misplaced reference source")
        paths.add(name)
        raw = source_bytes(package, name)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if len(raw) != source["bytes"] or sha(raw) != source["sha256"] or blob != source["git_blob_sha1"]:
            raise ValueError("Source lock mismatch: " + name)
        write(output / name, raw)
        entries.extend(index_source(source, raw, resource))
    write(output / "source-lock.json", source_bytes(package, "source-lock.json"))
    write(output / "resource.json", encoded(resource))
    write(output / "reference_reader.py", (TOOLS / "reference_reader.py").read_bytes())
    write(output / "README.md", source_bytes(package, "README.md"))
    write(output / "LICENSE.CPG", (TOOLS.parent / "LICENSE").read_bytes())
    entries.sort(key=lambda row: (row["upstream_path"], row["line"], row["kind"], row["title"]))
    write(output / "indexes/entries.jsonl", b"".join((json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode() for row in entries))
    counts = dict(sorted(Counter(row["kind"] for row in entries).items()))
    write(output / "indexes/summary.json", encoded({"resource_id": resource["id"], "source_files": len(lock["files"]),
          "index_entries": len(entries), "by_kind": counts, "scope": "static source references; no runtime registration claim"}))
    for expected in reference.get("index_expectations", []):
        if "count" in expected and counts.get(expected["kind"], 0) != expected["count"]:
            raise ValueError("Generated source index count differs from the reviewed resource contract")
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_dir():
            path.chmod(0o755)
        else:
            raw = path.read_bytes()
            rows.append({"path": path.relative_to(output).as_posix(), "bytes": len(raw), "mode": 0o644, "sha256": sha(raw)})
    inventory = {"schema_version": 1, "resource_id": resource["id"], "files": rows}
    write(output / "inventory.json", encoded(inventory)); output.chmod(0o755)
    return {"entity_id": resource["id"], "source_files": len(lock["files"]), "payload_files": len(rows) + 1,
            "payload_bytes": sum(row["bytes"] for row in rows) + (output / "inventory.json").stat().st_size,
            "inventory_sha256": sha(encoded(inventory)), "index_entries": len(entries), "index_kinds": counts}


def build(package: Path, output: Path, *, seal: bool = False) -> dict:
    package, output = package.resolve(), output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Use a new archive path")
    lock_path = package / "artifact-lock.json"
    if seal and lock_path.exists():
        raise FileExistsError("A sealed artifact identity cannot be replaced")
    if not seal and not lock_path.is_file():
        raise FileNotFoundError("An exact artifact lock is required for a rebuild")
    output.parent.mkdir(parents=True, exist_ok=True)
    reference = read_json(package / "reference.json"); spec = read_json(package / "package.json")
    if spec["id"] != reference["id"] or spec["version"] != reference["version"]:
        raise ValueError("Package definition differs from the original reference identity")
    with tempfile.TemporaryDirectory(prefix=".reference-material-", dir=output.parent) as temporary:
        payload = Path(temporary) / "payload"; built = build_payload(package, payload)
        contract = {"schema_version": 1, "entity_id": reference["id"], "version": reference["version"],
                    "commit": reference["commit"], "inventory_sha256": built["inventory_sha256"],
                    "source_files": built["source_files"], "payload_files": built["payload_files"],
                    "source_paths": sorted(row["upstream_path"] for row in read_json(package / "source-lock.json")["files"]),
                    "oracles": reference["oracles"], "index_expectations": reference.get("index_expectations", []),
                    "index_queries": reference.get("index_queries", [])}
        provenance = {"resource_id": reference["id"], "upstream_version": reference["version"],
                      "upstream_commit": reference["commit"], "source_lock_sha256": sha((package / "source-lock.json").read_bytes()),
                      "reader_sha256": sha((TOOLS / "reference_reader.py").read_bytes()),
                      "qualification_scope": "independent local reference reader"}
        if seal:
            for name, raw in (("recipe/qualification.json", encoded(contract)),
                              ("recipe/check.py", (TOOLS / "check_reference_material.py").read_bytes()),
                              ("packaging-provenance.json", encoded(provenance))):
                if (package / name).exists():
                    raise FileExistsError("Sealing must not replace an authored recipe: " + name)
                write(package / name, raw)
        elif (read_json(package / "recipe/qualification.json") != contract
              or read_json(package / "packaging-provenance.json") != provenance):
            raise ValueError("Regenerated inputs differ from the frozen recipe or provenance")
        receipt = pack(spec, output, method="material", payload=payload, recipe_dir=package / "recipe",
                       relocatable=True, provenance=provenance)
    if seal:
        write(lock_path, encoded({key: receipt[key] for key in ("id", "version", "build", "method", "bytes", "sha256", "manifest_sha256")}))
    else:
        expected = read_json(lock_path)
        for key in ("id", "version", "build", "method", "bytes", "sha256", "manifest_sha256"):
            if receipt[key] != expected[key]:
                raise ValueError("Rebuilt archive differs from the sealed identity: " + key)
        verify_package(output, expected_sha256=expected["sha256"], expected_bytes=expected["bytes"])
    return {"status": "passed", "artifact": receipt, "payload": built, "source_rebuild": not seal}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seal", action="store_true", help="Create the first recipe and immutable artifact lock for an unsealed resource")
    args = parser.parse_args()
    print(json.dumps(build(args.package, args.output, seal=args.seal), sort_keys=True, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
