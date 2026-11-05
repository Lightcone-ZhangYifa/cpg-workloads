"""Small standard-library helpers copied into each self-contained recipe."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback


def require(condition, description):
    if not condition:
        raise AssertionError(description)


def raises(exception, operation, description):
    try:
        operation()
    except exception:
        return
    raise AssertionError(description)


def installed_module(name):
    module = importlib.import_module(name)
    location = getattr(module, "__file__", None)
    require(location is not None, f"No inspectable module location: {name}")
    require(Path(location).resolve().is_relative_to(Path(sys.prefix).resolve()),
            f"Imported {name} from outside the selected environment: {location}")
    return module


def child(arguments, *, expected=0, cwd=None, input=None, timeout=60, environment=None):
    result = subprocess.run([str(arg) for arg in arguments], cwd=cwd, input=input,
                            text=True, capture_output=True, timeout=timeout,
                            env=environment)
    require(result.returncode == expected,
            f"Child returned {result.returncode}, expected {expected}: "
            f"{result.stdout[-2000:]} {result.stderr[-2000:]}")
    return result


def main(distribution, module_name, functional):
    parser = argparse.ArgumentParser(description=functional.__doc__)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    report = {"resource": 'py.dataset-import.xxhash', "status": "failed"}
    try:
        dist = importlib.metadata.distribution(distribution)
        location = Path(dist.locate_file("")).resolve()
        require(dist.version == args.expected_version,
                f"Expected {distribution} {args.expected_version}, found {dist.version}")
        require(location.is_relative_to(Path(sys.prefix).resolve()),
                "Distribution metadata is outside the selected environment")
        module = installed_module(module_name)
        report.update(version=dist.version, distribution_location=str(location),
                      module_location=module.__file__, interpreter=sys.executable)
        if args.version_only:
            report["checks"] = ["exact-distribution-and-module-location"]
        else:
            # Every check owns and removes only its temporary data directory.
            with tempfile.TemporaryDirectory(prefix="cpg-functional-", dir=Path.cwd()) as temporary:
                details = functional(module, Path(temporary))
            require(isinstance(details, dict), "Functional check must report its actual observations")
            require(bool(details.get("checks")), "An empty functional check cannot pass")
            report.update(details)
        report["status"] = "passed"
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
        traceback.print_exc(file=sys.stderr)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "passed" else 1
