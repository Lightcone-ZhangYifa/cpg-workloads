#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Read installed distribution metadata, file inventories and missing-package errors.'
    distribution = module.distribution("importlib-metadata")
    require(distribution.version == module.version("importlib_metadata"), "Normalized distribution lookup differs")
    require(distribution.metadata["Name"].lower().replace("_", "-") == "importlib-metadata", "Metadata name mismatch")
    require(bool(distribution.metadata["Requires-Python"]), "Python compatibility metadata missing")
    files = module.files("importlib-metadata")
    require(files and any(str(path).replace("\\", "/").endswith("importlib_metadata/__init__.py") for path in files), "Distribution file inventory missing module")
    package_files = [path for path in files if str(path).replace("\\", "/").endswith("importlib_metadata/__init__.py")]
    require(all(Path(distribution.locate_file(path)).is_file() for path in package_files), "Distribution file resolution failed")
    names = module.packages_distributions().get("importlib_metadata", [])
    require(any(name.lower().replace("_", "-") == "importlib-metadata" for name in names), "Import-to-distribution mapping failed")
    installed_module("zipp")
    raises(module.PackageNotFoundError, lambda: module.distribution("cpg-absent-distribution-421"), "Missing package metadata was fabricated")
    return {"checks": ["normalized-distribution-lookup", "metadata-fields", "installed-file-inventory", "file-location", "import-package-mapping", "locked-zipp-import", "missing-distribution"]}

if __name__ == '__main__':
    raise SystemExit(main('importlib-metadata', 'importlib_metadata', functional))
