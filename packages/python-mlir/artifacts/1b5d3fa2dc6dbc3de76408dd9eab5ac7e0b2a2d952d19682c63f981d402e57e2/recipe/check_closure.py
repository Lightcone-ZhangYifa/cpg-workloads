"""Validate the original Python dependency environment, not MLIR bindings."""
from __future__ import annotations
import argparse
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import sys
import tempfile


def check(lock):
    root = Path(sys.prefix).resolve()
    if root == Path(sys.base_prefix).resolve():
        raise AssertionError("A private virtual environment is required")
    checked_files = 0
    versions = {}
    for item in lock["distributions"]:
        dist = importlib.metadata.distribution(item["distribution"])
        if dist.version != item["version"]:
            raise AssertionError("Exact distribution version differs: " + item["distribution"])
        if not Path(dist.locate_file("")).resolve().is_relative_to(root):
            raise AssertionError("A dependency escaped the private prefix")
        versions[item["distribution"]] = dist.version
        record = dist.read_text("RECORD")
        if record is None:
            raise AssertionError("Missing wheel RECORD")
        for relative, encoded, size in csv.reader(io.StringIO(record)):
            if not encoded:
                continue
            path = Path(dist.locate_file(relative)).resolve()
            if not path.is_relative_to(root):
                raise AssertionError("RECORD entry escapes the selected environment")
            algorithm, expected = encoded.split("=", 1)
            actual = base64.urlsafe_b64encode(hashlib.new(algorithm, path.read_bytes()).digest()).rstrip(b"=").decode()
            if actual != expected or (size and path.stat().st_size != int(size)):
                raise AssertionError("Installed distribution content differs: " + relative)
            checked_files += 1

    import numpy as np
    import ml_dtypes
    import yaml
    import cffi
    from cryptography.hazmat.primitives import hashes
    from packaging.requirements import Requirement
    from pycparser import c_parser
    configuration = yaml.safe_load("pipeline: [canonicalize, cse]\ncosts: [1, 2, 3, 4]\n")
    values = np.array(configuration["costs"], dtype=ml_dtypes.bfloat16)
    if float(values.astype(np.float64).sum()) != 10.0:
        raise AssertionError("NumPy/ml-dtypes composition failed")
    ffi = cffi.FFI()
    ffi.cdef("int abs(int);")
    if ffi.dlopen(None).abs(-19) != 19:
        raise AssertionError("CFFI native call failed")
    parsed = c_parser.CParser().parse("int add(int a, int b) { return a+b; }")
    if parsed.ext[0].decl.name != "add":
        raise AssertionError("C parser result failed")
    hasher = hashes.Hash(hashes.SHA256())
    data = json.dumps(configuration, sort_keys=True).encode()
    hasher.update(data)
    if hasher.finalize() != hashlib.sha256(data).digest():
        raise AssertionError("Cryptography digest differs")
    requirement = Requirement("numpy>=2")
    if versions["numpy"] not in requirement.specifier:
        raise AssertionError("Packaging version constraint failed")
    try:
        yaml.safe_load("pipeline: [unterminated")
    except yaml.YAMLError:
        pass
    else:
        raise AssertionError("Invalid configuration was accepted")
    return {"status": "passed", "scope": "original python-mlir dependency capsule only; official MLIR bindings are not installed or qualified", "versions": versions, "record_files_verified": checked_files, "composition_checks": ["yaml-pipeline", "numpy-bfloat16-costs", "cffi-native-call", "c-parser-ast", "sha256-cross-check", "version-constraint", "malformed-yaml-rejection"], "prefix": str(root)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(json.loads(args.lock.read_text())), sort_keys=True))
