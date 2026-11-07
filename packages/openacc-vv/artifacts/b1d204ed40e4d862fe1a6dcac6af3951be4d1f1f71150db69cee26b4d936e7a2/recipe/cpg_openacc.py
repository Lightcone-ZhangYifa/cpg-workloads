"""Worker 056's bounded OpenACC interfaces. All execution uses local inputs.

This module is an adapter for upstream workloads, never a replacement package
manager. Upstream infrastructure.py and all upstream tests remain byte exact.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

EPCC_KERNELS = ["2MM", "3MM", "ATAX", "BICG", "MVT", "SYRK", "COV", "COR",
                "SYR2K", "GESUMMV", "GEMM", "2DCONV", "3DCONV", "27S", "HIMENO"]
VV_CORE = [n + ext for n in ["parallel_loop", "kernels_loop", "serial_loop",
    "parallel_if", "kernels_if", "serial_if", "loop_collapse", "routine_seq",
    "atomic_update_x_plus_expr", "data_copy_no_lower_bound",
    "enter_data_copyin_no_lower_bound", "acc_copyin"] for ext in [".c", ".cpp"]]
VV_EXPECTED_COMPILE_ERRORS = {"parallel_if.cpp", "routine_seq.c", "routine_seq.cpp"}
GNU_HOST_FLAGS = ["-O0", "-fopenacc", "-foffload=disable", "-lm"]
OPENACC_DATES = {201111: "1.0", 201306: "2.0", 201510: "2.5", 201711: "2.6",
    201811: "2.7", 201911: "3.0", 202011: "3.1", 202111: "3.2", 202211: "3.3",
    202506: "3.4"}


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def demand(condition, message):
    if not condition:
        raise RuntimeError(message)


def disjoint(first, second):
    a, b = Path(first).resolve(), Path(second).resolve()
    demand(a != b and a not in b.parents and b not in a.parents,
           f"Read-only inputs and writable work directory must be disjoint: {a}, {b}")


def execute(argv, cwd, timeout=120, env=None):
    """Record complete output; kill the process group on timeout."""
    start = time.monotonic()
    run_env = dict(os.environ, ACC_DEVICE_TYPE="host", PYTHONDONTWRITEBYTECODE="1")
    if env:
        run_env.update(env)
    p = subprocess.Popen([str(x) for x in argv], cwd=cwd, env=run_env,
                         text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    timed_out = False
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(p.pid, signal.SIGKILL)
        out, err = p.communicate()
    return {"argv": [str(x) for x in argv], "cwd": str(cwd),
            "returncode": p.returncode, "stdout": out, "stderr": err,
            "timeout": timed_out, "seconds": time.monotonic() - start}


def verify_upstream(base):
    base = Path(base)
    manifest = json.loads((base / "upstream-files.json").read_text())
    actual = {p.relative_to(base / "upstream").as_posix(): sha(p)
              for p in (base / "upstream").rglob("*") if p.is_file()}
    demand(actual == manifest["files"], "Upstream source inventory differs from the fixed commit")
    return {"status": "verified", "files": len(actual), "commit": manifest["commit"]}


def probe(compiler, work, language="c"):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    source = work / ("probe.cpp" if language == "cpp" else "probe.c")
    source.write_text('#include <stdio.h>\n#include <openacc.h>\n'
        '#ifndef _OPENACC\n#error OpenACC must be enabled\n#endif\n'
        'int main(void){acc_set_device_type(acc_device_host);'
        'printf("{\\"openacc_macro\\":%d,\\"gcc_major\\":%d,\\"gcc_minor\\":%d,'
        '\\"device_type\\":%d,\\"host_device_type\\":%d,\\"host_devices\\":%d}\\n",'
        '_OPENACC,__GNUC__,__GNUC_MINOR__,(int)acc_get_device_type(),'
        '(int)acc_device_host,acc_get_num_devices(acc_device_host));return 0;}\n')
    binary = work / "probe"
    build = execute([compiler, str(source), "-fopenacc", "-foffload=disable", "-o", str(binary)], work)
    dump(work / "compile.json", build)
    demand(build["returncode"] == 0, "The selected compiler cannot compile the OpenACC host probe")
    run = execute([binary], work)
    dump(work / "run.json", run)
    demand(run["returncode"] == 0, "OpenACC host device probe failed")
    result = json.loads(run["stdout"])
    demand(result["device_type"] == result["host_device_type"] and result["host_devices"] >= 1,
           "A real OpenACC host device must be active")
    demand(result["gcc_major"] == 13 and result["openacc_macro"] == 201711,
           "This bounded profile qualifies GNU 13/OpenACC 2.6 only; use the preserved upstream suite for another compiler")
    version = execute([compiler, "--version"], work)
    return {**result, "openacc_version": OPENACC_DATES[result["openacc_macro"]],
            "language": language, "compiler_path": shutil.which(compiler) or compiler,
            "compiler_version": version["stdout"].splitlines()[0],
            "compile": build, "run": run, "device": "host", "gpu_qualified": False}


def epcc_run(prefix, work, *, kernels=None, datasize=65536, seed=56):
    prefix, work = Path(prefix).resolve(), Path(work).resolve()
    disjoint(prefix, work)
    demand(type(datasize) is int and 65536 <= datasize <= 16777216,
           "datasize must be an integer from 65536 to 16777216 bytes")
    demand(type(seed) is int and 0 <= seed <= 4294967295, "seed must fit uint32")
    kernels = list(EPCC_KERNELS if kernels is None else kernels)
    demand(kernels and len(set(kernels)) == len(kernels) and set(kernels) <= set(EPCC_KERNELS),
           "Only distinct kernels in the declared host profile may be executed")
    work.mkdir(parents=True, exist_ok=False)
    source = prefix / "share/epcc-openacc"
    verification = verify_upstream(source)
    rows = []
    for kernel in kernels:
        result = execute([prefix / "bin/epcc-openacc-kernel", kernel, str(datasize), str(seed)], work, 30)
        row = {"kernel": kernel, "input": {"datasize_bytes": datasize, "seed": seed}, **result}
        if result["returncode"] == 0:
            value = json.loads(result["stdout"])
            demand(value["device_type"] == value["host_device_type"], "Unexpected execution device")
            demand(value["openacc"] == 201711 and math.isfinite(value["seconds"]), "Invalid execution measurement")
            row["measurement"] = value
            row["validation_scope"] = "upstream serial reference comparison" if kernel != "HIMENO" else "execution and finite timer only; no numerical oracle"
            row["status"] = "passed"
        else:
            row["status"] = "failed"
        rows.append(row)
    report = {"schema_version": 1, "resource": "epcc-openacc", "source": verification,
        "profile": "gnu13-openacc26-host", "device": "host", "gpu_qualified": False,
        "performance_qualified": False, "timing_unit": "seconds", "results": rows,
        "status": "passed" if all(r["status"] == "passed" for r in rows) else "failed"}
    dump(work / "results.json", report)
    return report


def all_vv_tags(source):
    tags = set()
    for p in (source / "Tests").iterdir():
        if p.suffix.lower() in {".c", ".cpp", ".f90"}:
            for line in p.read_text().splitlines():
                if re.match(r"(?://|!)T\d+:", line):
                    tags.update(t.strip() for t in line.split(":", 1)[1].split(",")
                                if t.strip() and ":" not in t)
    return sorted(tags)


def vv_config(source, work, cc="gcc", cxx="g++", fc=None, testdir=None, include_names=None):
    # The upstream implementation splits IncludeTags on spaces (the sample
    # documentation shows commas). Match executable behavior and verify counts.
    build = work / "build"
    build.mkdir(parents=True)
    lines = [f"CC:{cc}", f"CPP:{cxx}", "CCFlags:" + " ".join(GNU_HOST_FLAGS),
        "CPPFlags:" + " ".join(GNU_HOST_FLAGS), "C_ACC_Version:2.6", "CPP_ACC_Version:2.6",
        "IncludeTags:" + " ".join(all_vv_tags(source)), "TestDir:" + str(testdir or source / "Tests"),
        "BuildDir:" + str(build), "RuntimePrefix:env ACC_DEVICE_TYPE=host", "Fast:True", "Timeout:20",
        "Seed:56", "ResultsFormat:json", "ShowInfo", "KeepBuild"]
    if fc:
        lines.extend([f"FC:{fc}", "FCFlags:-O0 -fopenacc -foffload=disable -cpp -ffree-line-length-none -lm",
                      "Fortran_ACC_Version:2.6"])
    if include_names:
        lines.append("IncludeTests:" + " ".join(include_names))
    config = work / "config.txt"
    config.write_text("\n".join(lines) + "\n")
    return config


def normalize_vv(raw, *, expected=None):
    demand(isinstance(raw, dict) and isinstance(raw.get("runs"), dict), "Missing upstream runs object")
    demand(bool(raw["runs"]), "An empty upstream result is not a successful test run")
    if expected is not None:
        demand(set(raw["runs"]) == set(expected), "Missing or unexpected test records in upstream JSON")
    rows = []
    for name, attempts in sorted(raw["runs"].items()):
        demand(isinstance(attempts, list) and len(attempts) == 1,
               "The Fast profile requires exactly one compiler result per selected source")
        attempt = attempts[0]
        compilation = attempt.get("compilation", {})
        runtime = attempt.get("runtime", {})
        cc_rc, run_rc = compilation.get("result"), runtime.get("result")
        demand(type(cc_rc) is int, "Missing compiler return code for " + name)
        if cc_rc != 0:
            status = "compile_timeout" if compilation.get("runtime") == -1 else "compile_error"
            demand(run_rc is None, "A failed compilation unexpectedly has a runtime result")
        else:
            demand(type(run_rc) is int, "Successful compilation lacks an actual runtime result")
            status = "passed" if run_rc == 0 else "runtime_timeout" if runtime.get("runtime") == -1 else "runtime_error"
        rows.append({"name": name, "status": status, "compilation": compilation, "runtime": runtime})
    return rows


def run_upstream_vv(source, work, *, names=None, testdir=None, fc=None, cc="gcc", cxx="g++"):
    source, work = Path(source).resolve(), Path(work).resolve()
    disjoint(source, work)
    # The original suite launches shell commands without quoting. Refuse unsafe
    # whitespace/metacharacters instead of silently producing false evidence.
    for value in [str(source), str(work), cc, cxx] + ([fc] if fc else []):
        demand(bool(re.fullmatch(r"[A-Za-z0-9_./+\-]+", value)), "Upstream runner requires shell-safe paths/commands")
    work.mkdir(parents=True, exist_ok=False)
    config = vv_config(source, work, cc=cc, cxx=cxx, fc=fc, testdir=testdir)
    output = work / "upstream-results.json"
    command = [sys.executable, source / "infrastructure.py", "-c=" + str(config), "-o=" + str(output)]
    if names:
        command.extend(names)
    command_result = execute(command, work, timeout=1800)
    dump(work / "invocation.json", command_result)
    demand(command_result["returncode"] == 0 and not command_result["timeout"] and output.is_file(),
           "Upstream runner failed to produce a complete result")
    raw = json.loads(output.read_text())
    return normalize_vv(raw, expected=names)


def vv_run(prefix, work, *, full=False, fc=None, cc="gcc", cxx="g++"):
    prefix, work = Path(prefix).resolve(), Path(work).resolve()
    disjoint(prefix, work)
    work.mkdir(parents=True, exist_ok=False)
    base = prefix / "share/openacc-vv"
    verification = verify_upstream(base)
    probes = [probe(cc, work / "probe-c"), probe(cxx, work / "probe-cpp", "cpp")]
    selected = None if full else VV_CORE
    results = run_upstream_vv(base / "upstream", work / "suite", names=selected, fc=fc, cc=cc, cxx=cxx)
    counts = dict(Counter(r["status"] for r in results))
    report = {"schema_version": 1, "resource": "openacc-vv", "source": verification,
        "profile": "gnu13-openacc26-host-full" if full else "gnu13-openacc26-host-core24",
        "status": "completed", "device": "host", "gpu_qualified": False,
        "compiler_conformance_qualified": False, "specification_version": "2.6",
        "suite_versions": "see complete per-test metadata; this run filters to 2.6",
        "compiler_probes": probes, "fortran_compiler": fc,
        "counts": counts, "results": results,
        "exclusions": ["Versions other than 2.6 are filtered by upstream tags"] +
            ([] if fc else ["Fortran has no configured compiler and is not executed"])}
    dump(work / "results.json", report)
    return report


def vv_negatives(prefix, work):
    work = Path(work)
    work.mkdir()
    tests = work / "tests"
    tests.mkdir()
    fixtures = {
        "control.c": "int main(void){return 0;}",
        "compile_failure.c": "#error CPG intentional compile rejection\nint main(void){return 0;}",
        "runtime_failure.c": "int main(void){return 7;}"}
    for name, body in fixtures.items():
        (tests / name).write_text("#ifndef T1\n//T1:parallel,V:1.0-2.7\n" + body + "\n#endif\n")
    source = Path(prefix) / "share/openacc-vv/upstream"
    results = run_upstream_vv(source, work / "suite", names=list(fixtures), testdir=tests)
    classification = {r["name"]: r["status"] for r in results}
    expected = {"control.c": "passed", "compile_failure.c": "compile_error", "runtime_failure.c": "runtime_error"}
    demand(classification == expected, "Compiler/runtime negative controls were misclassified")
    rejected = {}
    for name, value, names in [
        ("empty_results", {"runs": {}}, None),
        ("missing_test", {"runs": {"a.c": [{"compilation": {"result": 0}, "runtime": {"result": 0}}]}}, ["a.c", "b.c"]),
        ("missing_runtime", {"runs": {"a.c": [{"compilation": {"result": 0}}]}}, ["a.c"])]:
        try:
            normalize_vv(value, expected=names)
        except RuntimeError as error:
            rejected[name] = str(error)
        else:
            raise RuntimeError("Malformed result was accepted: " + name)
    return {"status": "passed", "controlled_upstream_results": results, "malformed_results_rejected": rejected}


def epcc_negative(prefix, work):
    work = Path(work)
    work.mkdir()
    source = Path(prefix) / "share/epcc-openacc/upstream"
    text = (source / "level1.c").read_text()
    needle = "E[i*n+j] = tmp;"
    demand(needle in text, "Mutation anchor is missing")
    mutant = work / "level1-mutant.c"
    mutant.write_text("/* CPG negative control: deliberate output corruption, never an upstream patch. */\n" +
                      text.replace(needle, "E[i*n+j] = tmp + 1.0;", 1))
    driver = Path(prefix) / "share/epcc-openacc/adapter/epcc_driver.c"
    binary = work / "epcc-mutant"
    command = ["gcc", "-O2", "-fopenacc", "-fopenmp", "-foffload=disable", "-I", source,
        driver, mutant, source / "27stencil.c", source / "himeno.c", "-lm", "-o", binary]
    compilation = execute(command, work)
    demand(compilation["returncode"] == 0, "The negative-control mutant must compile")
    runtime = execute([binary, "2MM", "65536", "56"], work)
    demand(runtime["returncode"] != 0 and '"seconds":-11000' in runtime["stdout"],
           "Upstream serial oracle did not reject corrupted output")
    input_rejections = {}
    for label, args in {"negative_size": ["2MM", "-1", "56"], "unknown_kernel": ["SlicedD2H", "65536", "56"],
                        "missing_argument": ["2MM", "65536"], "bad_seed": ["2MM", "65536", "bad"]}.items():
        result = execute([Path(prefix) / "bin/epcc-openacc-kernel"] + args, work)
        demand(result["returncode"] in {64, 65}, "Invalid input was not rejected: " + label)
        input_rejections[label] = result
    return {"status": "passed", "mutation_source_sha256": sha(mutant), "compile": compilation,
            "run": runtime, "input_rejections": input_rejections}


def check(resource, prefix, work):
    prefix, work = Path(prefix).resolve(), Path(work).resolve()
    disjoint(prefix, work)
    work.mkdir(parents=True, exist_ok=False)
    if resource == "epcc-openacc":
        compiler = probe("gcc", work / "probe")
        reports = [epcc_run(prefix, work / f"run-{size}-{seed}", datasize=size, seed=seed)
                   for size, seed in [(65536, 56), (262144, 5601)]]
        demand(all(x["status"] == "passed" for x in reports), "EPCC host profile failed")
        negative = epcc_negative(prefix, work / "negative-controls")
        report = {"status": "passed", "resource": resource, "compiler": compiler,
                  "positive_executions": sum(len(r["results"]) for r in reports),
                  "numerically_checked_executions": sum(sum(x["kernel"] != "HIMENO" for x in r["results"]) for r in reports),
                  "reports": [str(work / f"run-{size}-{seed}/results.json") for size, seed in [(65536,56),(262144,5601)]],
                  "negative_controls": negative, "gpu_qualified": False, "performance_qualified": False}
    else:
        run = vv_run(prefix, work / "core24")
        outcomes = {r["name"]: r["status"] for r in run["results"]}
        expected = {name: ("compile_error" if name in VV_EXPECTED_COMPILE_ERRORS else "passed") for name in VV_CORE}
        demand(outcomes == expected, "Observed core compiler outcomes changed; inspect the emitted JSON instead of assuming qualification")
        report = {"status": "passed", "resource": resource, "core_tests": len(run["results"]),
            "compiler_outcomes": run["counts"], "negative_controls": vv_negatives(prefix, work / "negative-controls"),
            "gpu_qualified": False, "compiler_conformance_qualified": False}
    dump(work / "check.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource", choices=["epcc-openacc", "openacc-vv"])
    parser.add_argument("action", choices=["check", "run", "inventory"])
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--datasize", type=int, default=65536)
    parser.add_argument("--seed", type=int, default=56)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--fortran")
    args = parser.parse_args()
    if args.work_root is not None:
        demand(args.work is None, "Choose --work or --work-root")
        disjoint(args.prefix, args.work_root)
        args.work_root.mkdir(parents=True, exist_ok=True)
        args.work = Path(tempfile.mkdtemp(prefix="check-", dir=args.work_root)) / "run"
    if args.action == "inventory":
        print((args.prefix / f"share/{args.resource}/inventory.json").read_text())
        return 0
    if args.work is None:
        demand(args.action == "check", "run requires an explicit fresh --work directory")
        # Checks leave no generated files in the installed package.
        with tempfile.TemporaryDirectory(prefix="cpg-worker056-") as temporary:
            report = check(args.resource, args.prefix, Path(temporary) / "work")
    elif args.action == "check":
        report = check(args.resource, args.prefix, args.work)
    elif args.resource == "epcc-openacc":
        report = epcc_run(args.prefix, args.work, datasize=args.datasize, seed=args.seed)
    else:
        report = vv_run(args.prefix, args.work, full=args.full, fc=args.fortran)
    print(json.dumps({k: v for k, v in report.items() if k not in {"results", "compiler", "negative_controls"}}, sort_keys=True))
    return 0 if report["status"] in {"passed", "completed"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
