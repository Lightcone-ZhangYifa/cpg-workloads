#!/usr/bin/env python3
"""Known-answer local OTLP checks for the exact installed Collector release."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time
import traceback

VERSION = "0.163.1"
ARCHIVE_SHA256 = "e93e6fd2b59427420a9e8eba5b9e78260df6d21e95283a7298084d2aa07f9df7"
ARCHIVE_BYTES = 115292512
SIGNALS = {"logs": ("resourceLogs", "scopeLogs", "logRecords"),
           "traces": ("resourceSpans", "scopeSpans", "spans"),
           "metrics": ("resourceMetrics", "scopeMetrics", "metrics")}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def invoke(argv, root, label, expected=0):
    completed = subprocess.run([str(x) for x in argv], cwd=root, stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=45)
    (root / (label + ".stdout")).write_bytes(completed.stdout)
    (root / (label + ".stderr")).write_bytes(completed.stderr)
    save(root / (label + ".json"), {"argv": [str(x) for x in argv], "returncode": completed.returncode})
    if expected is None:
        need(completed.returncode != 0, label + " incorrectly succeeded")
    else:
        need(completed.returncode == expected, label + " returned " + str(completed.returncode))
    return completed


def identity(prefix, root, expected_version):
    need(expected_version == VERSION, "Unexpected requested Collector version")
    prefix = prefix.resolve(strict=True)
    profile = json.loads((prefix / "share/otelcol-contrib/profile.json").read_text())
    need(profile["resource_id"] == "otelcol-contrib-linux-amd64" and profile["version"] == VERSION,
         "Installed Collector profile identity differs")
    need(profile["archive_sha256"] == ARCHIVE_SHA256 and profile["archive_bytes"] == ARCHIVE_BYTES,
         "Collector profile does not identify the locked original input")
    release = prefix / "share/otelcol-contrib/release"
    binary = prefix / "bin/otelcol-contrib"
    need(binary.resolve(strict=True) == release / "otelcol-contrib", "Collector executable resolves outside its own release")
    need(digest(binary) == profile["binary_sha256"], "Installed Collector executable has changed")
    expected_files = profile["upstream_files"]
    need(len(expected_files) >= 2, "Collector release must retain the executable and upstream legal material")
    actual_files = [{"path": p.relative_to(release).as_posix(), "bytes": p.stat().st_size,
                     "sha256": digest(p), "mode": p.stat().st_mode & 0o777}
                    for p in sorted(release.rglob("*")) if p.is_file()]
    need(actual_files == expected_files, "Installed release files differ from the verified original member inventory")
    version = invoke([binary, "--version"], root, "version")
    version_text = (version.stdout + version.stderr).decode("utf-8", "replace")
    need(re.search(r"(?<![0-9.])" + re.escape(VERSION) + r"(?![0-9.])", version_text),
         "Installed Collector reports another version")
    return binary, profile


def configuration(root, port):
    # JSON is a YAML subset accepted by the native Collector file provider.
    return {"receivers": {"otlp": {"protocols": {"http": {"endpoint": "127.0.0.1:" + str(port)}}}},
            "processors": {"batch": {"timeout": "50ms", "send_batch_size": 1, "send_batch_max_size": 8}},
            "exporters": {"file/" + name: {"path": str(root / (name + ".otlp.jsonl")),
                                            "format": "json", "append": True, "flush_interval": "50ms"}
                          for name in SIGNALS},
            "service": {"telemetry": {"logs": {"level": "info", "encoding": "json"},
                                         "metrics": {"level": "none"}},
                        "pipelines": {name: {"receivers": ["otlp"], "processors": ["batch"],
                                               "exporters": ["file/" + name]} for name in SIGNALS}}}


def payloads():
    resource = {"attributes": [{"key": "service.name", "value": {"stringValue": "cpg-qualification"}}]}
    scope = {"name": "compiler-playground", "version": "qualification-v0200"}
    attribute = [{"key": "case", "value": {"stringValue": "known-answer"}}]
    point = {"attributes": attribute, "timeUnixNano": "1700000000000000000", "asInt": "42"}
    entries = {
        "logs": {"timeUnixNano": "1700000000000000000", "severityNumber": 9, "severityText": "INFO",
                 "body": {"stringValue": "cpg local log known answer"}, "attributes": attribute},
        "traces": {"traceId": "0102030405060708090a0b0c0d0e0f10", "spanId": "0102030405060708",
                   "name": "cpg-local-span", "kind": 1, "startTimeUnixNano": "1700000000000000000",
                   "endTimeUnixNano": "1700000000000000250", "attributes": attribute, "status": {"code": 1}},
        "metrics": {"name": "cpg.qualification.value", "description": "Known integer gauge", "unit": "1",
                    "gauge": {"dataPoints": [point]}}}
    return {name: {outer: [{"resource": resource, middle: [{"scope": scope, inner: [entries[name]]}]}]}
            for name, (outer, middle, inner) in SIGNALS.items()}


def request(port, name, body):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("POST", "/v1/" + name, body,
                           headers={"Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        return {"status": response.status, "body": response.read().decode("utf-8", "replace")}
    finally:
        connection.close()


def read_records(path, name):
    outer, middle, inner = SIGNALS[name]
    records, resources, scopes = [], [], []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        for resource in value.get(outer, []):
            resources.append(resource.get("resource"))
            for scope in resource.get(middle, []):
                scopes.append(scope.get("scope"))
                records.extend(scope.get(inner, []))
    return records, resources, scopes


def validate_records(root):
    result = {}
    for name in SIGNALS:
        records, resources, scopes = read_records(root / (name + ".otlp.jsonl"), name)
        need(len(records) == 1, "Expected exactly one known " + name + " record, observed " + str(len(records)))
        need(all(item == {"attributes": [{"key": "service.name", "value": {"stringValue": "cpg-qualification"}}]}
                 for item in resources), "Resource identity was not preserved")
        need(all(item.get("name") == "compiler-playground" and item.get("version") == "qualification-v0200"
                 for item in scopes), "Instrumentation scope identity was not preserved")
        record = records[0]
        if name == "logs":
            need(record.get("body") == {"stringValue": "cpg local log known answer"}
                 and record.get("severityNumber") == 9 and record.get("severityText") == "INFO"
                 and str(record.get("timeUnixNano")) == "1700000000000000000", "Log fields were not preserved")
        elif name == "traces":
            need(record.get("name") == "cpg-local-span" and record.get("traceId") == "0102030405060708090a0b0c0d0e0f10"
                 and record.get("spanId") == "0102030405060708" and record.get("kind") == 1,
                 "Span identity was not preserved")
            need(int(record["endTimeUnixNano"]) - int(record["startTimeUnixNano"]) == 250,
                 "Span timestamps were not preserved")
        else:
            need(record.get("name") == "cpg.qualification.value" and record.get("unit") == "1", "Metric identity differs")
            points = record.get("gauge", {}).get("dataPoints", [])
            need(len(points) == 1 and str(points[0].get("asInt")) == "42", "Known integer gauge was not preserved")
            need(str(points[0].get("timeUnixNano")) == "1700000000000000000", "Metric timestamp differs")
        attributes = record.get("gauge", {}).get("dataPoints", [record])[0].get("attributes")
        need(attributes == [{"key": "case", "value": {"stringValue": "known-answer"}}], "Known record attributes differ")
        result[name] = {"records": len(records), "file_sha256": digest(root / (name + ".otlp.jsonl"))}
    return result


def roundtrip(binary, root):
    components = invoke([binary, "components"], root, "components")
    text = (components.stdout + components.stderr).decode("utf-8", "replace")
    need(re.search(r"\botlp\b", text) and re.search(r"\bfile\b", text) and re.search(r"\bbatch\b", text),
         "Required receiver, processor and exporter are absent from the component inventory")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config = configuration(root, port)
    save(root / "collector.json", config)
    invoke([binary, "validate", "--config=" + str(root / "collector.json")], root, "config-valid")
    bad = json.loads(json.dumps(config))
    bad["service"]["pipelines"]["logs"]["exporters"] = ["missing-exporter"]
    save(root / "invalid-collector.json", bad)
    invalid = invoke([binary, "validate", "--config=" + str(root / "invalid-collector.json")],
                     root, "config-invalid", expected=None)
    need(b"missing-exporter" in invalid.stdout + invalid.stderr, "Wrong failure reason for malformed pipeline")
    proc = None
    lifecycle = {"scope": "Loopback HTTP receiver and local file exporters only", "pid": None,
                 "started": False, "reaped": False, "returncode": None, "forced_kill": False}
    try:
        with (root / "collector.stdout").open("wb") as stdout, (root / "collector.stderr").open("wb") as stderr:
            proc = subprocess.Popen([str(binary), "--config=" + str(root / "collector.json")], cwd=root,
                                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            lifecycle.update(pid=proc.pid, started=True)
            deadline = time.monotonic() + 25
            while True:
                need(proc.poll() is None, "Collector exited before its receiver became ready")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except (OSError, TimeoutError):
                    need(time.monotonic() < deadline, "Collector receiver did not become ready")
                    time.sleep(0.05)
            responses = {}
            for name, payload in payloads().items():
                save(root / (name + ".request.json"), payload)
                responses[name] = request(port, name, json.dumps(payload).encode())
                need(responses[name]["status"] == 200, "Valid " + name + " request was rejected")
                body = json.loads(responses[name]["body"])
                need(not body.get("partialSuccess"), "Collector returned partial success")
            responses["malformed"] = request(port, "logs", b"{not valid JSON")
            need(responses["malformed"]["status"] == 400, "Malformed OTLP JSON was not rejected with HTTP 400")
            save(root / "http-responses.json", responses)
            deadline = time.monotonic() + 20
            while not all((root / (name + ".otlp.jsonl")).exists()
                          and (root / (name + ".otlp.jsonl")).stat().st_size for name in SIGNALS):
                need(proc.poll() is None, "Collector exited while exporting known records")
                need(time.monotonic() < deadline, "Collector did not export all three signals")
                time.sleep(0.05)
            proc.send_signal(signal.SIGTERM)
            lifecycle["returncode"] = proc.wait(timeout=15)
            lifecycle["reaped"] = True
            need(proc.returncode == 0, "Collector did not shut down gracefully")
        records = validate_records(root)
        return {"signals": records, "invalid_config_rejected": True, "malformed_http_json_rejected": True,
                "collector_returncode": proc.returncode, "collector_reaped": True}
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    lifecycle["forced_kill"] = True
                    proc.kill()
                    proc.wait(timeout=10)
            lifecycle.update(returncode=proc.returncode, reaped=proc.poll() is not None)
        save(root / "lifecycle.json", lifecycle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--expected-version", default=VERSION)
    parser.add_argument("--case", choices=["version", "collector"], default="collector")
    args = parser.parse_args()
    args.build.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="otel-" + args.case + "-", dir=args.build))
    summary = {"schema_version": 1, "resource_id": "otelcol-contrib-linux-amd64", "case": args.case,
               "status": "failed", "evidence": str(root), "version": VERSION,
               "scope": "Native Linux amd64 release; loopback OTLP/HTTP logs, spans and integer gauge; no production backend, OCI or Go source rebuild"}
    try:
        binary, profile = identity(args.prefix, root, args.expected_version)
        summary["binary_sha256"] = profile["binary_sha256"]
        summary["original_release_files"] = len(profile["upstream_files"])
        if args.case == "collector":
            summary.update(roundtrip(binary, root))
        summary["status"] = "passed"
        save(root / "summary.json", summary)
        print(json.dumps(summary, sort_keys=True))
    except BaseException as error:
        summary["error"] = type(error).__name__ + ": " + str(error)
        save(root / "summary.json", summary)
        raise


if __name__ == "__main__":
    main()
