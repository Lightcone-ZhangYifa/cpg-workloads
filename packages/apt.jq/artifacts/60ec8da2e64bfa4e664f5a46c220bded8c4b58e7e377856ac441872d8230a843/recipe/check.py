#!/usr/bin/env python3
"""Validate jq JSON transformation, streaming, argument handling and failure exits."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def validate_aggregation(value):
    expected = [{"compiler": "cproc", "total_ns": 10, "count": 1},
                {"compiler": "qbe", "total_ns": 14, "count": 2}]
    if value != expected:
        raise ValueError("The filtered, grouped JSON aggregation is incorrect")


def qualify(args, evidence):
    launcher = [str(args.tool)]
    if args.loader:
        if not args.library_path:
            raise ValueError("A private loader requires its matching private library path")
        launcher = [str(args.loader), "--library-path", args.library_path, str(args.tool)]
    commands = evidence.setdefault("commands", [])

    def run(arguments, data=None, expected=0):
        argv = launcher + arguments
        result = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=20,
                                env=dict(os.environ, LC_ALL="C"), check=False)
        commands.append({"argv": argv, "stdin": data, "returncode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != expected:
            raise ValueError(f"Expected exit {expected}; observed {result.returncode}")
        return result

    version = run(["--version"]).stdout.strip()
    if version != "jq-" + args.expected_version:
        raise ValueError("The selected jq upstream version differs: " + version)
    if args.version_only:
        return {"status": "passed", "check": "tool-reported-version", "version": version, **evidence}
    records = [{"compiler": "qbe", "ns": 6, "valid": True}, {"compiler": "qbe", "ns": 8, "valid": True},
               {"compiler": "cproc", "ns": 10, "valid": True}, {"compiler": "qbe", "ns": 999, "valid": False}]
    program = '[.[] | select(.valid)] | group_by(.compiler) | map({compiler: .[0].compiler, total_ns: (map(.ns) | add), count: length})'
    aggregation = json.loads(run(["-c", program], json.dumps(records)).stdout)
    validate_aggregation(aggregation)
    tag = 'literal "quote", $name, newline\n and Unicode \u7f16\u8bd1'
    if json.loads(run(["-nc", "--arg", "tag", tag, "$tag"]).stdout) != tag:
        raise ValueError("The --arg value was not preserved literally")
    streamed = run(["--stream", "-c", "select(length == 2)"], '{"rows":[{"x":2},{"x":4}],"empty":[]}')
    leaves = [json.loads(line) for line in streamed.stdout.splitlines()]
    if leaves != [[["rows", 0, "x"], 2], [["rows", 1, "x"], 4], [["empty"], []]]:
        raise ValueError("The streaming path/value records differ")
    if json.loads(run(["-nc", '"compiler42" | capture("compiler(?<number>[0-9]+)")']).stdout) != {"number": "42"}:
        raise ValueError("The linked regular-expression engine did not decode the capture")
    if run(["-ne", "false"], expected=1).stdout.strip() != "false":
        raise ValueError("The false result did not preserve jq -e semantics")
    if run(["-ne", "empty"], expected=4).stdout:
        raise ValueError("The empty result unexpectedly emitted data")
    malformed = run(["."], "{", expected=4)
    compiled = run(["-n", "["], expected=3)
    if not malformed.stderr or not compiled.stderr:
        raise ValueError("Malformed JSON or filter diagnostics are missing")
    run(["-n", "halt_error(7)"], expected=7)
    return {"status": "passed", "check": "json-transform-stream-and-exit-contract", "version": version,
            "aggregation": aggregation, "streamed_leaves": leaves, **evidence,
            "scope": "Locked jq JSON/filter operations, Oniguruma capture and documented exit statuses; not arbitrary numeric-precision guarantees."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", type=Path, default=Path("/usr/bin/jq"))
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--library-path")
    parser.add_argument("--expected-version", default="1.7")
    parser.add_argument("--version-only", action="store_true")
    evidence = {}
    try:
        result = qualify(parser.parse_args(), evidence)
    except Exception as error:
        result = {"status": "failed", "reason": str(error), "error_type": type(error).__name__, **evidence}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
