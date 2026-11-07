#!/usr/bin/env python3
"""Original CPG PackageManager hook: keep evidence outside the installed tree."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import uuid


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-base", type=Path, required=True)
    options = parser.parse_args()
    options.output_base.mkdir(parents=True, exist_ok=True)
    output = options.output_base / uuid.uuid4().hex
    command = [sys.executable, "-B", "-I", str(Path(__file__).with_name("verify_libcst.py")),
               "--output", str(output)]
    raise SystemExit(subprocess.run(command, check=False, timeout=90).returncode)
