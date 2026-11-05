#!/usr/bin/env python3
"""Execute Clang capability checks using explicitly supplied local LLVM roots.

This module never downloads, installs, resolves packages, or edits CPG catalogs.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

from lsp_client import LSPClient, position_of

BASELINE_PIN = "7a941dfb2877a0b8cf30323fefa85ad019e0b0f5"
CATALOG_SHA256 = "d176f73bc6d6a04dd5e9c38167afd78181d1dfad5e866ec7abd8176a99eb9d8c"
ENTITY_ID = "llvm-feature.clang-and-clang-tools"
HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


class Checks:
    def __init__(self, llvm_root: Path, output: Path):
        self.llvm_root = llvm_root
        self.output = output
        self.logs = output / "logs"
        self.logs.mkdir(parents=True)
        self.env = os.environ.copy()
        self.env.update({"LC_ALL": "C", "XDG_CACHE_HOME": str(output / "cache"),
                         "LLVM_DISABLE_CRASH_REPORT": "1"})
        self.commands = []
        self.clang = llvm_root / "bin/clang"
        self.clangxx = llvm_root / "bin/clang++"
        self.clangd = llvm_root / "bin/clangd"

    def command(self, name: str, argv, *, cwd: Path | None = None,
                expect: int | None = 0, timeout: float = 120):
        argv = [str(item) for item in argv]
        cwd = cwd or self.output
        start = time.monotonic()
        timed_out = False
        try:
            result = subprocess.run(argv, cwd=cwd, env=self.env, capture_output=True,
                                    timeout=timeout, check=False)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code, stdout, stderr = 124, exc.stdout or b"", exc.stderr or b""
        (self.logs / f"{name}.stdout").write_bytes(stdout)
        (self.logs / f"{name}.stderr").write_bytes(stderr)
        entry = {"name": name, "argv": argv, "cwd": str(cwd), "returncode": code,
                 "duration_seconds": round(time.monotonic() - start, 6),
                 "timed_out": timed_out, "stdout": f"logs/{name}.stdout",
                 "stderr": f"logs/{name}.stderr"}
        self.commands.append(entry)
        write_json(self.output / "commands.json", self.commands)
        if expect is not None and code != expect:
            raise RuntimeError(f"{name} returned {code}; see {entry['stderr']}")
        return code, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    def identity(self):
        result = {}
        for name, exe in (("clang", self.clang), ("clangd", self.clangd)):
            _, text, _ = self.command(f"identity-{name}", [exe, "--version"])
            if BASELINE_PIN not in text:
                raise ValueError(f"{name} does not identify the locked baseline source pin")
            result[name] = {"path": str(exe), "version_output": text,
                            "sha256": sha256(exe.resolve())}
        shared_library = (self.llvm_root / "lib/libclang-cpp.so").resolve()
        result["libclang_cpp"] = {"path": str(shared_library), "sha256": sha256(shared_library)}
        config = self.llvm_root / "include/clang/Config/config.h"
        result["clang_build_config"] = {"path": str(config), "sha256": sha256(config),
                                         "cir_enabled": "#define CLANG_ENABLE_CIR 1" in config.read_text()}
        return result

    def tooling(self):
        directory = self.output / "clang_tooling"
        shutil.copytree(HERE / "fixtures/clang_tooling", directory)
        source = directory / "input.cpp"
        helper = self.output / "semantic-rewrite"
        self.command("build-semantic-rewrite", [self.clangxx, "-std=c++17", "-O1", "-fno-rtti",
                     f"-I{self.llvm_root / 'include'}", HERE / "src/semantic_rewrite.cpp",
                     f"-L{self.llvm_root / 'lib'}", f"-Wl,-rpath,{self.llvm_root / 'lib'}",
                     "-lclang-cpp", "-o", helper])
        common = [str(self.clangxx), "-std=c++17", "-DCPG_REAL_COMPILE_COMMAND=1"]
        before_command = common + ["-c", str(source), "-o", str(directory / "before.o")]
        write_json(directory / "compile_commands.json", [{"directory": str(directory),
                   "file": str(source), "arguments": before_command}])
        self.command("compile-database-command", before_command, cwd=directory)
        self.command("link-before", [self.clangxx, directory / "before.o", "-o", directory / "before"])
        self.command("run-before", [directory / "before"])
        _, transformed, rewrite_log = self.command("semantic-rewrite", [helper, "--expected-count=2", "-p", directory, source])
        original = source.read_text()
        expected = original.replace("int a = cpg::old_api(3);", "int a = ::cpg::new_api(3);")
        expected = expected.replace("int b = old_api(4);", "int b = ::cpg::new_api(4);")
        assert transformed == expected, "Changes exceeded the exact two permitted semantic call sites"
        assert "CPG_REWRITE_COUNT=2" in rewrite_log, "Expected exactly two AST matches"
        rewritten = directory / "rewritten.cpp"
        rewritten.write_text(transformed)
        (directory / "rewrite.patch").write_text("".join(difflib.unified_diff(
            original.splitlines(keepends=True), transformed.splitlines(keepends=True),
            fromfile="input.cpp", tofile="rewritten.cpp")))
        self.command("compile-after", common + [str(rewritten), "-o", str(directory / "after")])
        self.command("run-after", [directory / "after"])
        second_command = common + ["-c", str(rewritten), "-o", str(directory / "rewritten.o")]
        write_json(directory / "compile_commands.json", [
            {"directory": str(directory), "file": str(source), "arguments": before_command},
            {"directory": str(directory), "file": str(rewritten), "arguments": second_command}])
        self.command("compile-second-database-command", second_command)
        _, second, second_log = self.command("rewrite-idempotence", [helper, "-p", directory, rewritten])
        assert second == transformed and "CPG_REWRITE_COUNT=0" in second_log
        missing = directory / "empty_database"
        missing.mkdir()
        write_json(missing / "compile_commands.json", [])
        code, _, _ = self.command("reject-missing-compdb-entry", [helper, "-p", missing, source], expect=None)
        assert code != 0, "Missing compile commands must fail closed"
        no_define = self.command("reject-missing-required-define", [self.clangxx, "-fsyntax-only", source], expect=None)
        assert no_define[0] != 0
        mismatch = self.command("reject-count-mismatch", [helper, "--expected-count=3", "-p", directory, source], expect=None)
        assert mismatch[0] == 5 and mismatch[1] == "", "Unexpected match counts must not emit changed source"
        invalid = self.command("reject-invalid-target-name", [helper, "--to-qualified=::cpg::new_api(); bad()", "-p", directory, source], expect=None)
        assert invalid[0] == 2 and invalid[1] == "", "Replacement must be a qualified identifier"
        return {"record_id": "review.engineering.clang-source-tooling", "status": "passed",
                "source_pin": BASELINE_PIN, "rewrite_count": 2,
                "checks": ["real_compile_database_command_executed", "libtooling_astmatchers_transformer",
                           "exact_int_overload_only", "other_namespace_preserved", "member_preserved",
                           "double_overload_preserved", "macro_preserved", "comment_and_string_preserved",
                           "exact_unmatched_bytes_preserved", "recompiled_and_executed_before_after",
                           "idempotent", "missing_database_rejected", "database_define_required",
                           "unexpected_match_count_rejected", "invalid_replacement_identifier_rejected"],
                "patch": "clang_tooling/rewrite.patch"}

    def language_server(self):
        directory = self.output / "clangd"
        shutil.copytree(HERE / "fixtures/clangd", directory)
        source_paths = [directory / "src" / name for name in ("api.cpp", "main.cpp", "broken.cpp")]
        common = [str(self.clangxx), "-std=c++17", "-DCPG_REAL_COMPILE_COMMAND=1",
                  f"-I{directory / 'include'}"]
        entries = [{"directory": str(directory), "file": str(p),
                    "arguments": common + ["-c", str(p), "-o", str(p.with_suffix(".o"))]}
                   for p in source_paths]
        write_json(directory / "compile_commands.json", entries)
        for entry in entries[:2]:
            self.command("clangd-fixture-compile-" + Path(entry["file"]).stem, entry["arguments"], cwd=directory)
        self.command("clangd-fixture-link", [self.clangxx, *(p.with_suffix(".o") for p in source_paths[:2]),
                                           "-o", directory / "fixture"])
        self.command("clangd-fixture-execute", [directory / "fixture"])
        negative_code, _, _ = self.command("clangd-fixture-negative-compile", entries[2]["arguments"], expect=None)
        assert negative_code != 0, "Invalid fixture must fail the real compiler"
        argv = [str(self.clangd), f"--compile-commands-dir={directory}", "--background-index", "-j=2",
                "--pch-storage=memory", "--enable-config=false", "--log=verbose"]
        uri_main = source_paths[1].as_uri()
        uri_api = source_paths[0].as_uri()
        uri_broken = source_paths[2].as_uri()
        with LSPClient(argv, directory, self.logs, self.env) as client:
            initialize = client.request("initialize", {"processId": os.getpid(), "rootUri": directory.as_uri(),
                      "capabilities": {"textDocument": {"publishDiagnostics": {"versionSupport": True},
                                                     "definition": {"linkSupport": True}}},
                      "initializationOptions": {"clangdFileStatus": True}})
            client.send("initialized", {})
            for path in source_paths:
                client.send("textDocument/didOpen", {"textDocument": {"uri": path.as_uri(),
                            "languageId": "cpp", "version": 1, "text": path.read_text()}})
            clean_api = client.diagnostics(uri_api, 1)
            clean_main = client.diagnostics(uri_main, 1)
            broken_diagnostics = client.diagnostics(uri_broken, 1)
            assert not any(d.get("severity") == 1 for d in clean_api + clean_main)
            assert any(d.get("severity") == 1 for d in broken_diagnostics)
            assert any(d.get("code") == "init_conversion_failed" and
                       d.get("range", {}).get("start", {}).get("line") == 2
                       for d in broken_diagnostics), "Expected the actual argument-type diagnostic"
            main_pos = position_of(source_paths[1].read_text(), "add(19")
            definitions = client.request("textDocument/definition", {"textDocument": {"uri": uri_main},
                                                                     "position": main_pos})
            def_uris = [item.get("targetUri", item.get("uri")) for item in definitions or []]
            assert uri_api in def_uris, f"Definition must cross to implementation TU, got {def_uris}"
            references = client.request("textDocument/references", {"textDocument": {"uri": uri_api},
                                      "position": position_of(source_paths[0].read_text(), "add(int"),
                                      "context": {"includeDeclaration": True}})
            ref_uris = {item["uri"] for item in references or []}
            assert uri_main in ref_uris and uri_api in ref_uris, "References must include both translation units"
            fixed = source_paths[2].read_text().replace('"wrong-type"', "2")
            client.send("textDocument/didChange", {"textDocument": {"uri": uri_broken, "version": 2},
                                                  "contentChanges": [{"text": fixed}]})
            fixed_diagnostics = client.diagnostics(uri_broken, 2)
            assert not any(d.get("severity") == 1 for d in fixed_diagnostics)
            response_data = {"initialize": initialize, "diagnostics": broken_diagnostics,
                             "diagnostics_after_fix": fixed_diagnostics,
                             "definitions": definitions, "references": references}
            write_json(directory / "lsp-results.json", response_data)
        assert client.process.returncode == 0, "clangd must exit normally after shutdown"
        server_log = (self.logs / "clangd.stderr.log").read_text(errors="replace")
        assert "CPG_REAL_COMPILE_COMMAND" in server_log and "compile_commands.json" in server_log
        return {"record_id": "review.engineering.clangd", "status": "passed", "source_pin": BASELINE_PIN,
                "checks": ["stdio_lsp_initialize_shutdown", "real_compile_database_flags",
                           "positive_compile_and_execution", "clean_diagnostics_for_valid_TUs",
                           "type_error_diagnostic", "cross_TU_definition", "cross_TU_references",
                           "versioned_diagnostic_clears_after_fix"],
                "evidence": ["clangd/lsp-results.json", "logs/lsp-messages.jsonl", "logs/clangd.stderr.log"]}

    def cir(self, root: Path | None = None, supplemental_pin: str | None = None):
        directory = self.output / "cir"
        shutil.copytree(HERE / "fixtures/cir", directory)
        root = root or self.llvm_root
        compiler = root / "bin/clang"
        _, version, _ = self.command("cir-identity", [compiler, "--version"])
        expected_pin = supplemental_pin or BASELINE_PIN
        if expected_pin not in version:
            raise ValueError("CIR compiler does not match its explicit source pin")
        source = directory / "pipeline.c"
        cir_file = directory / "pipeline.cir"
        code, _, error = self.command("cir-emit", [compiler, "-fclangir", "-emit-cir", source,
                                                   "-o", cir_file], expect=None)
        identity = {"source_pin": expected_pin, "version_output": version,
                    "compiler_sha256": sha256(compiler.resolve()),
                    "baseline_pin_unchanged": BASELINE_PIN,
                    "variant": "baseline" if expected_pin == BASELINE_PIN else "supplemental"}
        if code:
            return {"record_id": "review.engineering.clangir", "status": "blocked", **identity,
                    "reason": error.strip(), "checks": ["real_emit_cir_probe_failed"],
                    "required": "A local LLVM build that enables CLANG_ENABLE_CIR; no execution-time downloads"}
        text = cir_file.read_text()
        assert "cir.func" in text and "square" in text
        llvm_file = directory / "pipeline.ll"
        self.command("cir-to-llvm", [compiler, "-x", "cir", "-S", "-emit-llvm", cir_file, "-o", llvm_file])
        assert "define" in llvm_file.read_text() and "square" in llvm_file.read_text()
        self.command("cir-llvm-link", [compiler, llvm_file, "-o", directory / "from-cir"])
        self.command("cir-program", [directory / "from-cir"])
        self.command("cir-native-reference", [self.clang, source, "-o", directory / "native"])
        self.command("cir-native-program", [directory / "native"])
        return {"record_id": "review.engineering.clangir", "status": "passed", **identity,
                "checks": ["emit_cir", "explicit_cir_file_to_llvm_ir", "llvm_ir_recompiled",
                           "native_and_cir_programs_executed"],
                "evidence": ["cir/pipeline.cir", "cir/pipeline.ll"]}


def validate(llvm_root: Path, output: Path, *, cir_root: Path | None = None,
             cir_pin: str | None = None) -> dict:
    """Python API: validate local capabilities and return a structured report.

    The caller owns toolchain preparation. A new output directory is required.
    No global registry or installation state is modified.
    """
    if bool(cir_root) != bool(cir_pin):
        raise ValueError("cir_root and cir_pin must be supplied together")
    if cir_pin and (len(cir_pin) != 40 or any(c not in "0123456789abcdef" for c in cir_pin)):
        raise ValueError("cir_pin must be a full lower-case Git commit SHA")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    checks = Checks(Path(llvm_root).resolve(), output)
    report = {"schema_version": 1, "entity_id": ENTITY_ID,
              "baseline_pin": BASELINE_PIN,
              "baseline_catalog_sha256": CATALOG_SHA256, "new_resource_count": 0,
              "network_activity": "none in runner; caller supplies prepared local toolchains",
              "host": {"platform": platform.platform(), "machine": platform.machine()},
              "implementation_sha256": {
                  str(path.relative_to(HERE)): sha256(path)
                  for path in sorted([*HERE.glob("*.py"), *HERE.glob("src/*.cpp"),
                                      *(p for p in (HERE / "fixtures").rglob("*") if p.is_file())])},
              "capabilities": []}
    try:
        report["toolchain"] = checks.identity()
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        write_json(output / "report.json", report)
        return report
    operations = [("review.engineering.clang-source-tooling", checks.tooling),
                  ("review.engineering.clangd", checks.language_server),
                  ("review.engineering.clangir", lambda: checks.cir(
                      Path(cir_root).resolve() if cir_root else None, cir_pin))]
    for record_id, operation in operations:
        try:
            result = operation()
        except Exception as exc:
            result = {"record_id": record_id, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
            (checks.logs / (record_id.rsplit(".", 1)[-1] + ".exception.log")).write_text(traceback.format_exc())
        report["capabilities"].append(result)
        write_json(output / "report.json", report)
    statuses = [item["status"] for item in report["capabilities"]]
    report["status"] = "failed" if "failed" in statuses else "partial" if "blocked" in statuses else "passed"
    report["passed_capabilities"] = statuses.count("passed")
    report["assigned_capabilities"] = 3
    write_json(output / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="A new output directory")
    parser.add_argument("--cir-root", type=Path)
    parser.add_argument("--cir-pin", help="Full immutable source commit for an explicit supplemental CIR build")
    args = parser.parse_args()
    try:
        report = validate(args.llvm_root, args.output, cir_root=args.cir_root, cir_pin=args.cir_pin)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"passed": 0, "partial": 2, "failed": 1}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
