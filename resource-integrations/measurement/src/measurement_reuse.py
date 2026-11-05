"""Consume existing CPG measurement tools without installing or requalifying them.

Only raw accepted samples enter normalized timings. Original documents remain
authoritative; this module does not promote a resource's formal qualification.
Python 3.10+, standard library only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import random
import signal
import statistics
import subprocess
import time
from typing import Any, Callable


class MeasurementError(ValueError):
    """Input cannot support the requested measurement claim."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MeasurementError(message)


def number(value: Any, name: str, *, zero: bool = False) -> float:
    require(type(value) in (float, int), f"{name}: expected a number, not {type(value).__name__}")
    result = float(value)
    require(math.isfinite(result), f"{name}: must be finite")
    require(result >= 0 if zero else result > 0, f"{name}: must be {'nonnegative' if zero else 'positive'}")
    return result


def nonempty_text(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value), f"{name}: expected nonempty text")
    return value


def sample_list(values: Any, name: str, *, zero: bool = False) -> list[float]:
    require(isinstance(values, list) and bool(values), f"{name}: raw samples are required")
    return [number(v, f"{name}[{i}]", zero=zero) for i, v in enumerate(values)]


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json_bytes(raw: bytes) -> dict[str, Any]:
    def bad_constant(value: str) -> None:
        raise MeasurementError(f"nonfinite JSON constant: {value}")
    result = json.loads(raw, object_pairs_hook=_json_pairs,
                        parse_constant=bad_constant)
    require(isinstance(result, dict), "top-level JSON must be an object")
    return result


def load_json(path: Path) -> dict[str, Any]:
    return parse_json_bytes(path.read_bytes())


def _record(tool: str, name: str, values: list[float], context: dict[str, Any],
            *, unit: str = "second", raw_indices: Any = None) -> dict[str, Any]:
    require(bool(values), f"{name}: no accepted samples")
    return {"resource_id": tool, "benchmark": name, "unit": unit,
            "samples": values, "sample_count": len(values),
            "median": statistics.median(values), "context": context,
            "raw_indices": raw_indices,
            "scope": "accepted raw timing samples; no correctness or speedup claim"}


def parse_google_benchmark(doc: dict[str, Any]) -> list[dict[str, Any]]:
    context = doc.get("context")
    rows = doc.get("benchmarks")
    require(isinstance(context, dict), "Google Benchmark context is required")
    schema = context.get("json_schema_version", 1)
    require(type(schema) is int and schema == 1, "unsupported Google Benchmark JSON schema")
    require(isinstance(rows, list) and bool(rows), "Google Benchmark rows are required")
    factors = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
    grouped: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows):
        require(isinstance(row, dict), f"benchmark row {i}: expected object")
        require(not row.get("error_occurred") and not row.get("skipped"), f"benchmark row {i}: failed or skipped")
        kind = row.get("run_type", "iteration")
        require(kind in ("iteration", "aggregate"), f"benchmark row {i}: unsupported run_type")
        if kind == "aggregate":
            continue
        name = nonempty_text(row.get("run_name", row.get("name")), "benchmark name")
        require(type(row.get("iterations")) is int and row["iterations"] > 0,
                f"{name}: positive iteration count required")
        unit = row.get("time_unit")
        require(unit in factors, f"{name}: unknown time unit")
        real = number(row.get("real_time"), f"{name}.real_time") * factors[unit]
        cpu = number(row.get("cpu_time"), f"{name}.cpu_time", zero=True) * factors[unit]
        bucket = grouped.setdefault(name, {"real": [], "cpu": [], "rows": [], "iterations": []})
        bucket["real"].append(real)
        bucket["cpu"].append(cpu)
        bucket["rows"].append(i)
        bucket["iterations"].append(row["iterations"])
    require(bool(grouped), "aggregate-only Google Benchmark output cannot substitute for raw samples")
    return [_record("google-benchmark", name, b["real"],
                    {"upstream": context, "cpu_seconds": b["cpu"],
                     "iterations": b["iterations"], "sample_semantics": "per-iteration real_time; already normalized"},
                    raw_indices=b["rows"]) for name, b in grouped.items()]


def parse_hyperfine(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = doc.get("results")
    require(isinstance(rows, list) and bool(rows), "hyperfine results are required")
    result = []
    for i, row in enumerate(rows):
        require(isinstance(row, dict), f"hyperfine row {i}: expected object")
        name = nonempty_text(row.get("command"), "hyperfine command")
        times = sample_list(row.get("times"), f"{name}.times")
        exits = row.get("exit_codes")
        require(isinstance(exits, list) and len(exits) == len(times), f"{name}: one exit code per timing required")
        require(all(type(v) is int and v == 0 for v in exits), f"{name}: nonzero or invalid exit code")
        result.append(_record("apt.hyperfine", name, times,
                              {"upstream_row": i, "exit_codes": exits,
                               "parameters": row.get("parameters"),
                               "sample_semantics": "seconds; preserve hyperfine shell policy and warmup command separately"},
                              raw_indices=list(range(len(times)))))
    return result


def parse_pyperf(doc: dict[str, Any]) -> list[dict[str, Any]]:
    require(doc.get("version") == "1.0", "only pyperf JSON format 1.0 is supported")
    rows = doc.get("benchmarks")
    common = doc.get("metadata", {})
    require(isinstance(common, dict), "pyperf common metadata must be an object")
    require(isinstance(rows, list) and bool(rows), "pyperf benchmarks are required")
    result = []
    seen_names = set()
    for i, bench in enumerate(rows):
        require(isinstance(bench, dict), f"pyperf benchmark {i}: expected object")
        meta = bench.get("metadata", {})
        require(isinstance(meta, dict), "pyperf benchmark metadata must be an object")
        meta = {**common, **meta}
        runs = bench.get("runs")
        require(isinstance(runs, list) and bool(runs), "pyperf runs are required")
        accepted, run_details, indices, names = [], [], [], set()
        for j, run in enumerate(runs):
            require(isinstance(run, dict) and isinstance(run.get("metadata", {}), dict), "invalid pyperf run")
            m = {**meta, **run.get("metadata", {})}
            names.add(nonempty_text(m.get("name"), "pyperf name"))
            require(m.get("unit", "second") == "second", "pyperf non-time values cannot be treated as seconds")
            loops = m.get("loops", 1)
            inner_loops = m.get("inner_loops", 1)
            require(type(loops) is int and loops > 0 and type(inner_loops) is int and inner_loops > 0,
                    "pyperf loops must be positive integers")
            warmups = run.get("warmups", [])
            require(isinstance(warmups, list), "pyperf warmups must be a list")
            for w in warmups:
                require(isinstance(w, (list, tuple)) and len(w) == 2 and type(w[0]) is int and w[0] > 0,
                        "invalid pyperf warmup pair")
                number(w[1], "pyperf warmup", zero=True)
            calibration = any(m.get(k) for k in ("calibrate_loops", "recalibrate_loops", "calibrate_warmups", "recalibrate_warmups"))
            values = run.get("values", [])
            require(isinstance(values, list), "pyperf values must be a list")
            checked = [number(v, f"pyperf runs[{j}].values[{k}]") for k, v in enumerate(values)]
            if not calibration:
                accepted.extend(checked)
                indices.extend([[j, k] for k in range(len(checked))])
            run_details.append({"run": j, "metadata": m, "warmups": warmups,
                                "calibration": bool(calibration), "accepted_values": 0 if calibration else len(checked)})
        require(len(names) == 1, "pyperf name changed between runs")
        name = next(iter(names))
        require(name not in seen_names, "duplicate pyperf benchmark name")
        seen_names.add(name)
        result.append(_record("py.pyperf", name, accepted,
                              {"runs": run_details, "sample_semantics": "values already divided by loops and inner_loops; no second division"},
                              raw_indices=indices))
    return result


def parse_asv(doc: dict[str, Any], benchmark_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    require(type(doc.get("version")) is int and doc["version"] == 2, "only ASV result schema 2 is supported")
    cols = doc.get("result_columns")
    require(isinstance(cols, list) and all(isinstance(x, str) for x in cols), "ASV result_columns required")
    require(len(cols) == len(set(cols)), "duplicate ASV result columns")
    require({"result", "params", "version", "samples"}.issubset(cols), "ASV raw sample/version columns required")
    rows = doc.get("results")
    require(isinstance(rows, dict) and bool(rows), "ASV results required")
    nonempty_text(doc.get("commit_hash"), "ASV project commit")
    nonempty_text(doc.get("env_name"), "ASV environment")
    result = []
    for name, values in rows.items():
        nonempty_text(name, "ASV benchmark name")
        require(isinstance(values, list) and len(values) <= len(cols), "invalid ASV column row")
        row = dict(zip(cols, values))
        definition = benchmark_catalog.get(name)
        require(isinstance(definition, dict), f"{name}: benchmark definition required for units/version")
        require(definition.get("type") in ("time", "timeraw") and definition.get("unit") == "seconds",
                f"{name}: only explicitly timed benchmarks use seconds")
        require(row.get("version") is not None and row["version"] == definition.get("version"),
                f"{name}: missing or mismatched benchmark version")
        params = row.get("params")
        require(isinstance(params, list) and all(isinstance(p, list) and p for p in params), "invalid ASV parameter grid")
        require(params == definition.get("params", []), f"{name}: parameter grid changed")
        combinations = list(itertools.product(*params)) if params else [()]
        summaries, raw_samples = row.get("result"), row.get("samples")
        require(isinstance(summaries, list) and len(summaries) == len(combinations), "ASV result cardinality mismatch")
        require(isinstance(raw_samples, list) and len(raw_samples) == len(combinations),
                f"{name}: raw samples missing (use --record-samples)")
        for j, combination in enumerate(combinations):
            number(summaries[j], f"{name}: failed, skipped, or nonfinite ASV result")
            samples = sample_list(raw_samples[j], f"{name}.samples[{j}]")
            label = name if not combination else name + "/" + json.dumps(combination, ensure_ascii=False, separators=(",", ":"))
            result.append(_record("py.asv", label, samples,
                                  {"commit_hash": doc["commit_hash"], "env_name": doc["env_name"],
                                   "benchmark_version": row["version"], "parameters": list(combination),
                                   "host": doc.get("params", {}), "requirements": doc.get("requirements", {}),
                                   "sample_semantics": "normalized per-call samples; summary statistics excluded"},
                                  raw_indices=[[name, j, k] for k in range(len(samples))]))
    return result


def parse_gnu_time(text: str) -> list[dict[str, Any]]:
    lines = [line for line in text.splitlines() if line.startswith("CPG_TIME_V1\t")]
    require(len(lines) == 1, "exactly one GNU time record required; use a dedicated output file per process")
    fields = lines[0].split("\t")
    require(len(fields) == 6, "expected CPG_TIME_V1, %e, %U, %S, %M, %x")
    try:
        wall, user, system = (float(x) for x in fields[1:4])
        rss, exit_code = int(fields[4]), int(fields[5])
    except ValueError as exc:
        raise MeasurementError("invalid GNU time number or locale (use LC_ALL=C)") from exc
    require(exit_code == 0, f"GNU time child failed with exit code {exit_code}")
    for label, value in (("wall", wall), ("user", user), ("system", system)):
        number(value, label, zero=True)
    require(rss >= 0, "negative maximum resident set")
    return [_record("apt.time", "process", [wall],
                    {"user_seconds": user, "system_seconds": system, "max_rss_kib": rss,
                     "exit_code": exit_code, "below_report_resolution": wall == 0,
                     "sample_semantics": "external process elapsed time; zero is below report resolution, never an infinite speedup"})]


def normalize(resource: str, source: Path, *, catalog: Path | None = None) -> dict[str, Any]:
    raw = source.read_bytes()
    catalog_identity = None
    if resource == "apt.time":
        records = parse_gnu_time(raw.decode("utf-8"))
    else:
        doc = parse_json_bytes(raw)
        if resource == "py.asv":
            require(catalog is not None, "ASV needs --catalog benchmarks.json")
            catalog_raw = catalog.read_bytes()
            records = parse_asv(doc, parse_json_bytes(catalog_raw))
            catalog_identity = {"file": str(catalog), "sha256": hashlib.sha256(catalog_raw).hexdigest()}
        else:
            parsers = {"google-benchmark": parse_google_benchmark,
                       "apt.hyperfine": parse_hyperfine, "py.pyperf": parse_pyperf}
            require(resource in parsers, "unsupported resource")
            records = parsers[resource](doc)
    return {"schema_version": 1, "resource_id": resource, "source_file": str(source),
            "source_sha256": hashlib.sha256(raw).hexdigest(), "catalog": catalog_identity,
            "records": records, "formal_qualification_changed": False}


def host_state() -> dict[str, Any]:
    def read(path: str) -> str | None:
        try:
            return Path(path).read_text().strip()
        except (OSError, UnicodeError):
            return None
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    governors = {}
    if affinity:
        for cpu in affinity:
            v = read(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor")
            if v is not None:
                governors[str(cpu)] = v
    return {"utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
            "cpu_affinity": affinity, "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "governors": governors,
            "intel_pstate_no_turbo": read("/sys/devices/system/cpu/intel_pstate/no_turbo"),
            "cpufreq_boost": read("/sys/devices/system/cpu/cpufreq/boost"),
            "cgroup_cpu_max": read("/sys/fs/cgroup/cpu.max"),
            "cgroup_cpu_stat": read("/sys/fs/cgroup/cpu.stat"),
            "clock": {"implementation": time.get_clock_info("perf_counter").implementation,
                      "resolution": time.get_clock_info("perf_counter").resolution},
            "system_performance_profiler": None,
            "scope": "read-only host metadata, no tuning and no profiler"}


def paired_plan(blocks: int, seed: int) -> list[list[str]]:
    require(type(blocks) is int and blocks >= 2 and blocks % 2 == 0, "blocks must be an even integer >= 2")
    require(type(seed) is int, "seed must be an integer")
    orders = [["baseline", "candidate"] for _ in range(blocks // 2)] + [["candidate", "baseline"] for _ in range(blocks // 2)]
    random.Random(seed).shuffle(orders)
    return orders


def _argv(value: Any) -> list[str]:
    require(isinstance(value, list) and bool(value) and all(isinstance(x, str) and "\x00" not in x for x in value),
            "command must be a nonempty argv list, never shell text")
    require(Path(value[0]).is_absolute(), "executable must be an absolute path")
    require(Path(value[0]).is_file(), "executable does not exist")
    return value


def _group_exists(pgid: int) -> bool | None:
    """Probe our PID namespace through the kernel, never a host /proc mount.

    A zombie can keep a process group present until reaped. In that case we
    conservatively refuse to confirm cleanup rather than ignore the residue.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return None
    return True


def _kill_group(pgid: int) -> str | None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return None  # Completion raced the timeout/cleanup observation.
    except OSError as exc:
        return str(exc)
    return None


def _run_one(argv: list[str], timeout: float,
             record: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    begin = time.perf_counter_ns()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, "LC_ALL": "C"}, start_new_session=True)
    timed_out = False
    interruption = None
    cleanup_error = None
    communication_complete = True
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit) as exc:
        timed_out = isinstance(exc, subprocess.TimeoutExpired)
        if not timed_out:
            interruption = exc
        if os.name == "posix":
            cleanup_error = _kill_group(proc.pid)
        else:
            proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired as exc:
            # A child that escaped the group can retain pipes. Do not block
            # indefinitely or accept the measurement as clean.
            communication_complete = False
            stdout, stderr = exc.output or b"", exc.stderr or b""
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                cleanup_error = cleanup_error or "direct child did not exit after termination"
    elapsed = (time.perf_counter_ns() - begin) / 1e9
    cleanup_begin = time.perf_counter_ns()
    group_before = _group_exists(proc.pid) if os.name == "posix" else None
    unexpected_descendants = group_before is True and not timed_out
    if group_before:
        cleanup_error = _kill_group(proc.pid) or cleanup_error
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            remaining = _group_exists(proc.pid)
            if remaining is not True:
                break
            time.sleep(.01)
    remaining = _group_exists(proc.pid) if os.name == "posix" else None
    cleanup_confirmed = (remaining is False and communication_complete and cleanup_error is None)
    row = {"argv": argv, "returncode": proc.returncode, "timeout": timed_out,
            "interrupted": type(interruption).__name__ if interruption is not None else None,
            "wall_seconds": elapsed, "stdout": stdout.decode("utf-8", "replace"),
            "stderr": stderr.decode("utf-8", "replace"),
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "cleanup": {"confirmed": cleanup_confirmed, "unexpected_descendants": unexpected_descendants,
                        "owned_pgid": proc.pid, "process_group_present_before": group_before,
                        "process_group_present_after": remaining,
                        "error": cleanup_error, "seconds": (time.perf_counter_ns() - cleanup_begin) / 1e9,
                        "scope": "owned Linux process group only; detached sessions need CPG target lifecycle management"}}
    if record is not None:
        record(row)
    if interruption is not None:
        raise interruption
    return row


def run_pairs(spec: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Run explicit commands in balanced randomized paired blocks, fail closed.

    Every invocation must return the predeclared exact expected stdout digest.
    Application-specific output normalization should be done by a transparent
    wrapper before this API. This API measures whole-process elapsed time.
    """
    require(not destination.exists(), "output destination already exists")
    argv = {name: _argv(spec.get(name)) for name in ("baseline", "candidate")}
    blocks, seed = spec.get("blocks", 6), spec.get("seed", 3501)
    orders = paired_plan(blocks, seed)
    warmups = spec.get("warmups", 1)
    require(type(warmups) is int and warmups >= 0, "warmups must be a nonnegative integer")
    timeout = number(spec.get("timeout_seconds", 30.0), "timeout_seconds")
    expected = spec.get("expected_stdout_sha256")
    require(isinstance(expected, str) and len(expected) == 64 and all(c in "0123456789abcdef" for c in expected),
            "predeclared expected stdout SHA-256 is required")
    destination.mkdir(parents=True)
    report: dict[str, Any] = {"schema_version": 1, "seed": seed, "blocks": blocks,
            "orders": orders, "warmups_per_variant": warmups, "spec": spec,
            "host_before": host_state(), "invocations": [], "accepted": False,
            "scope": "whole-process wall time; measured here using stdlib, not a run of the five reused tools",
            "executable_sha256": {k: hashlib.sha256(Path(v[0]).read_bytes()).hexdigest() for k, v in argv.items()}}
    def invoke(kind: str, block: int | None, variant: str) -> dict[str, Any]:
        state = host_state()
        def record(row: dict[str, Any]) -> None:
            row.update(kind=kind, block=block, variant=variant, host_before=state, host_after=host_state())
            row["correct"] = (row["returncode"] == 0 and not row["timeout"] and row["stdout_sha256"] == expected
                              and row["interrupted"] is None and row["cleanup"]["confirmed"]
                              and not row["cleanup"]["unexpected_descendants"])
            report["invocations"].append(row)
            with (destination / "raw-invocations.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        row = _run_one(argv[variant], timeout, record)
        require(row["correct"], f"{variant}: nonzero exit, timeout, correctness mismatch, unexpected child, or unconfirmed cleanup")
        return row
    try:
        for variant in ("baseline", "candidate"):
            invoke("preflight", None, variant)
        for _ in range(warmups):
            for variant in ("baseline", "candidate"):
                invoke("warmup", None, variant)
        pairs = []
        for block, order in enumerate(orders):
            timings = {variant: invoke("measurement", block, variant)["wall_seconds"] for variant in order}
            ratio = number(timings["baseline"], "baseline elapsed") / number(timings["candidate"], "candidate elapsed")
            pairs.append({"block": block, **timings, "baseline_over_candidate": ratio})
        report.update(accepted=True, pairs=pairs,
                      paired_geometric_ratio=math.exp(statistics.mean(math.log(x["baseline_over_candidate"]) for x in pairs)),
                      uncertainty="No significance or speedup conclusion; short-run shared-host demonstration.")
    except (MeasurementError, OSError, KeyboardInterrupt, SystemExit) as exc:
        report["error"] = str(exc) or type(exc).__name__
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            report["interrupted"] = type(exc).__name__
        raise
    finally:
        report["host_after"] = host_state()
        (destination / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    normalize_parser = sub.add_parser("normalize")
    normalize_parser.add_argument("resource", choices=["py.asv", "py.pyperf", "google-benchmark", "apt.hyperfine", "apt.time"])
    normalize_parser.add_argument("source", type=Path)
    normalize_parser.add_argument("--catalog", type=Path)
    pairs = sub.add_parser("pairs")
    pairs.add_argument("spec", type=Path)
    pairs.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        value = normalize(args.resource, args.source, catalog=args.catalog) if args.command == "normalize" else run_pairs(load_json(args.spec), args.destination)
    except (MeasurementError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"measurement rejected: {exc}\n")
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
