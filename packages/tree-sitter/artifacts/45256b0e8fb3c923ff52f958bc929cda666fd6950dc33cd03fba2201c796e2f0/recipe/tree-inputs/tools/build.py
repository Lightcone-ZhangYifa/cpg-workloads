#!/usr/bin/env python3
"""Build the pinned C runtime and generated language parsers using local inputs only."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 2:
                continue
            target = destination.joinpath(*parts[1:])
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Archive traversal: " + member.name)
            if member.issym() or member.islnk():
                raise ValueError("Unexpected archive link: " + member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                content = source.extractfile(member)
                assert content is not None
                target.write_bytes(content.read())
                target.chmod(member.mode & 0o777)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "sources")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--prefix", type=Path, default=ROOT / "install")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "evidence")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    args = parser.parse_args()
    source_dir, build_dir, prefix, evidence_dir = (
        p.resolve() for p in (args.source_dir, args.build_dir, args.prefix, args.evidence_dir)
    )
    # Separate mutable roles so a consumer never builds inside an installation.
    roles = (source_dir, build_dir, prefix)
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(roles) for b in roles[i + 1:]):
        raise ValueError("source, build, and install directories must be separate and non-nested")
    for directory in (source_dir, build_dir, prefix / "lib", prefix / "bin", prefix / "include/tree_sitter", evidence_dir):
        directory.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "source-lock.json").read_text())
    manifest = []
    for artifact in lock["artifacts"]:
        archive = ROOT / artifact["path"]
        if not archive.is_file() or digest(archive) != artifact["sha256"]:
            raise RuntimeError("Missing or corrupt offline input: " + str(archive))
        if artifact["id"] == "tree-sitter-cli":
            if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
                raise RuntimeError("Included CLI is Linux x86_64 only; native runtime sources are portable")
            binary = prefix / "bin/tree-sitter"
            binary.write_bytes(gzip.decompress(archive.read_bytes()))
            binary.chmod(0o755)
        else:
            destination = source_dir / artifact["id"]
            # Preserve the earlier source tree if extraction fails (for example
            # when disk space is exhausted). No unverified partial source is used.
            stage = Path(tempfile.mkdtemp(prefix="." + artifact["id"] + "-", dir=source_dir))
            try:
                extract(archive, stage)
                if destination.exists():
                    shutil.rmtree(destination)
                stage.rename(destination)
            except BaseException:
                shutil.rmtree(stage, ignore_errors=True)
                raise
            for path in sorted(destination.rglob("*")):
                if path.is_file():
                    manifest.append({"path": str(path.relative_to(source_dir)), "bytes": path.stat().st_size, "sha256": digest(path)})
    (evidence_dir / "source-files.json").write_text(json.dumps(manifest, indent=2) + "\n")
    commands = []

    def run(command: list[str], name: str) -> None:
        started = time.monotonic()
        result = subprocess.run(command, cwd=build_dir, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        elapsed = time.monotonic() - started
        (evidence_dir / (name + ".log")).write_text(result.stdout)
        commands.append({"name": name, "argv": command, "cwd": str(build_dir), "returncode": result.returncode, "seconds": elapsed})
        if result.returncode:
            raise RuntimeError(name + " failed; see " + str(evidence_dir / (name + ".log")))

    runtime = source_dir / "tree-sitter/lib"
    run([args.cc, "-std=c11", "-O2", "-fPIC", "-shared", "-D_DEFAULT_SOURCE", "-I", str(runtime / "include"), "-I", str(runtime / "src"), str(runtime / "src/lib.c"), "-o", str(build_dir / "libtree-sitter.so")], "build-runtime")
    shutil.copy2(build_dir / "libtree-sitter.so", prefix / "lib/libtree-sitter.so")
    shutil.copy2(runtime / "include/tree_sitter/api.h", prefix / "include/tree_sitter/api.h")
    for lang in ("c", "cpp", "rust"):
        grammar = source_dir / ("tree-sitter-" + lang)
        sources = [str(grammar / "src/parser.c")]
        scanner = grammar / "src/scanner.c"
        if scanner.exists():
            sources.append(str(scanner))
        output = build_dir / ("libtree-sitter-" + lang + ".so")
        run([args.cc, "-std=c11", "-O2", "-fPIC", "-shared", "-I", str(grammar / "src"), *sources, "-o", str(output)], "build-" + lang)
        shutil.copy2(output, prefix / "lib" / output.name)
    licenses = prefix / "licenses"
    licenses.mkdir(exist_ok=True)
    for path in source_dir.rglob("LICENSE*"):
        if path.is_file():
            out = licenses / str(path.relative_to(source_dir)).replace("/", "__")
            shutil.copy2(path, out)
    run([args.cc, "--version"], "compiler-version")
    run([str(prefix / "bin/tree-sitter"), "--version"], "cli-version")
    receipt = {
        "status": "passed", "network_required": False, "source_lock_sha256": digest(ROOT / "source-lock.json"),
        "platform": platform.platform(), "commands": commands,
        "prefix": str(prefix), "source_dir": str(source_dir), "build_dir": str(build_dir),
        "outputs": [{"path": str(p.relative_to(prefix)), "sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(prefix.rglob("*")) if p.is_file()],
        "scope": "Native C runtime and pre-generated C/C++/Rust parsers compiled from source; CLI is official prebuilt, not a local Rust build."
    }
    (evidence_dir / "build-result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": "passed", "prefix": str(prefix), "command_count": len(commands)}))


if __name__ == "__main__":
    main()
