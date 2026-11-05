"""Check installed ITT APIs using the unchanged upstream text/JSON oracle."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

CPP_TESTS = ("test_string_handle", "test_domain", "test_task", "test_region",
             "test_frame", "test_collection_control", "test_thread_naming", "test_ittapi")
ORACLE_SHA = "74a47309829844187278d1d8565701928d288c90d5683b4d429fe7eb1060c65e"


def clean_environment():
    return {k: v for k, v in dict(os.environ, LC_ALL="C", PYTHONDONTWRITEBYTECODE="1").items()
            if not k.startswith("INTEL_LIBITTNOTIFY") and k not in {"LD_LIBRARY_PATH", "LD_PRELOAD"}}


def traces(directory):
    rows = []
    for p in sorted(Path(directory).rglob("*")):
        if p.is_file():
            raw = p.read_bytes()
            rows.append({"path": p.relative_to(directory).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(),
                         "bytes": len(raw), "content": raw.decode("utf-8", "strict")})
    return rows


def check(prefix, case):
    prefix = Path(prefix).resolve(strict=True)
    share = prefix / "share/ittapi"
    probes = share / "qualification"
    profile = json.loads((share / "profile.json").read_text())
    if profile.get("version") != "3.28.4" or profile.get("upstream_commit") != "bd72cfb15e34a5fc4c0a8d10f5bb5305d60e1eec":
        raise RuntimeError("Installed resource identity differs from the pinned release")
    header = (prefix / "include/ittnotify.h").read_text()
    if re.search(r"#define ITT_MAJOR\s+3\b", header) is None or re.search(r"#define ITT_MINOR\s+0\b", header) is None:
        raise RuntimeError("Installed C header ABI identity differs")
    if hashlib.sha256((probes / "official_refcol_test.py").read_bytes()).hexdigest() != ORACLE_SHA:
        raise RuntimeError("The official collector oracle was changed")
    if case == "version":
        config = (prefix / "lib/cmake/ittapi/ittapiConfigVersion.cmake").read_text()
        if 'set(PACKAGE_VERSION "3.0.0")' not in config:
            raise RuntimeError("Installed upstream CMake ABI version differs")
        return {"status": "passed", "release": "3.28.4", "c_api": "3.0", "cmake_config_version": "3.0.0",
                "python_distribution": "not_installed", "fortran_module_compiler": profile["gnu_fortran_compiler"]}
    commands, evidence = [], []
    env = clean_environment()
    collector = prefix / "lib/libittnotify_refcol.so"
    def run(argv, *, environment=None, expected=0):
        row = {"argv": [str(x) for x in argv]}
        result = subprocess.run(row["argv"], env=environment or env, capture_output=True, text=True, timeout=120)
        row.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        commands.append(row)
        # Preserve every completed command even if a later assertion fails.
        print(json.dumps({"command_evidence": row}), file=sys.stderr, flush=True)
        if (expected == 0 and result.returncode != 0) or (expected == "nonzero" and result.returncode == 0):
            raise RuntimeError("ITT probe returned an unexpected status: " + json.dumps(row))
        return result
    with tempfile.TemporaryDirectory(prefix="cpg-ittapi-check-") as temporary:
        work = Path(temporary)
        if case == "collector":
            if profile.get("cpp_tests") != list(CPP_TESTS) or len(profile.get("cpp_tests", [])) != 8:
                raise RuntimeError("The complete fixed upstream C++ test inventory is required")
            for name in CPP_TESTS:
                run([probes / name])
            logdir = work / "official"
            logdir.mkdir()
            run([sys.executable, probes / "official_refcol_test.py", "--lib", collector,
                 "--exe", prefix / "bin/refcol_smoke_test", "--log-dir", logdir])
            evidence.extend(traces(logdir))
            broken = work / "missing-collector"
            broken.mkdir()
            run([sys.executable, probes / "official_refcol_test.py", "--lib", work / "nonexistent.so",
                 "--exe", prefix / "bin/refcol_smoke_test", "--log-dir", broken], expected="nonzero")
            unusable = work / "valid-file-without-collector"
            unusable.mkdir()
            negative = run([sys.executable, probes / "official_refcol_test.py", "--lib", probes / "advisor_fixture.so",
                            "--exe", prefix / "bin/refcol_smoke_test", "--log-dir", unusable], expected="nonzero")
            if "no .log file" not in negative.stdout and "no .json file" not in negative.stdout:
                raise RuntimeError("Missing-collector negative did not exercise missing trace validation")
            cppdir = work / "cpp"
            cppdir.mkdir()
            run([probes / "cpp_probe"], environment=dict(env, INTEL_LIBITTNOTIFY64=str(collector),
                INTEL_LIBITTNOTIFY_LOG_DIR=str(cppdir), INTEL_LIBITTNOTIFY_GEN_JSON="1"))
            files = list(cppdir.glob("*.json"))
            if len(files) != 1:
                raise RuntimeError("C++ wrapper did not produce exactly one collector JSON trace")
            events = json.loads(files[0].read_text())
            tasks = [e for e in events if e.get("name") == "cpg-cpp-task"]
            if [e.get("ph") for e in tasks] != ["B", "E"]:
                raise RuntimeError("C++ task begin/end did not reach the official collector")
            evidence.extend(traces(cppdir))
            scope = "Eight exact upstream C++ regressions; official 18-symbol text and 10-phase JSON oracle; C++ RAII task trace; missing-path and valid-file-without-collector rejection."
        elif case == "fortran":
            for mode in ("text", "json"):
                logdir = work / mode
                logdir.mkdir()
                runtime = dict(env, INTEL_LIBITTNOTIFY64=str(collector), INTEL_LIBITTNOTIFY_LOG_DIR=str(logdir))
                if mode == "json":
                    runtime["INTEL_LIBITTNOTIFY_GEN_JSON"] = "1"
                run([probes / "fortran_probe"], environment=runtime)
                files = list(logdir.glob("*." + ("json" if mode == "json" else "log")))
                if len(files) != 1:
                    raise RuntimeError("Fortran calls did not create the expected official collector trace")
                if mode == "text":
                    content = files[0].read_text()
                    if not all(token in content for token in ("__itt_thread_set_name", "cpg-fortran-worker", "__itt_pause", "__itt_resume")):
                        raise RuntimeError("Fortran pointer bindings did not reach all expected C entry points")
                else:
                    events = json.loads(files[0].read_text())
                    names = [e.get("args", {}).get("api") for e in events if e.get("ph") == "i"]
                    if names != ["pause", "resume"] or not any(e.get("ph") == "M" and e.get("args", {}).get("name") == "cpg-fortran-worker" for e in events):
                        raise RuntimeError("Fortran JSON trace is missing thread metadata or ordered pause/resume")
                evidence.extend(traces(logdir))
            sync = run([probes / "sync_probe"])
            if sync.stdout.strip() != "sync-create:64-bit-address:null-type:cpg-sync:mutex":
                raise RuntimeError("Four-argument sync_create pointer ABI fixture failed")
            advisor = run([probes / "advisor_probe"], environment=dict(env, INTEL_LIBITTNOTIFY64=str(probes / "advisor_fixture.so")))
            expected = ["advisor:site_begin:cpg-site", "advisor:task_begin:cpg-task", "advisor:iteration_task:cpg-iteration",
                        "advisor:lock_acquire:17", "advisor:lock_release:17", "advisor:disable_push:0", "advisor:disable_pop",
                        "advisor:disable_push:1", "advisor:disable_pop"]
            for operation in ("induction", "reduction", "observe", "clear"):
                expected.extend(f"advisor:{operation}:{i}:{size}" for i, size in enumerate((2,4,8,4,8,8,16)))
            expected.extend(["advisor:aggregate:9", "advisor:task_end", "advisor:site_end"])
            if advisor.stdout.splitlines() != expected:
                raise RuntimeError("Advisor ABI fixture did not receive the full typed sequence")
            # A real loaded library without __itt_model_* must safely use the
            # existing stubs; an empty trace is NOT counted as delivered events.
            fallbackdir = work / "advisor-unsupported"
            fallbackdir.mkdir()
            unsupported = run([probes / "advisor_probe"], environment=dict(env, INTEL_LIBITTNOTIFY64=str(collector),
                              INTEL_LIBITTNOTIFY_LOG_DIR=str(fallbackdir)))
            if "advisor:" in unsupported.stdout:
                raise RuntimeError("Unsupported collector was mistaken for the Advisor ABI fixture")
            missing = run([probes / "advisor_probe"], environment=dict(env, INTEL_LIBITTNOTIFY64=str(work / "absent.so")))
            if "advisor:" in missing.stdout:
                raise RuntimeError("Missing collector was incorrectly treated as event delivery")
            scope = "GNU ITT module delivers thread/pause/resume to official text+JSON collector; typed sync_create high-address fixture; 14 Advisor symbols including 28 typed memory calls; missing-symbol fallback is no-op only."
        else:
            raise ValueError("Unknown check case")
    return {"status": "passed", "case": case, "scope": scope, "commands": commands, "traces": evidence,
            "advisor_profiler": "not_qualified", "performance_score": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--case", choices=("version", "collector", "fortran"), required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.prefix, args.case), indent=2))


if __name__ == "__main__":
    main()
