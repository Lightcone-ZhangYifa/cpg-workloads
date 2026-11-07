"""Run the declared bounded profile from the actual installed prefix."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", type=Path, required=True)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--recipe", type=Path, required=True)
    a = p.parse_args()
    if sys.flags.optimize:
        raise RuntimeError("Run without -O: upstream validation relies on assertions")
    config = json.loads((a.recipe / "resource.json").read_text())
    local = a.prefix / "env/bin/python"
    if config["wheels"] and not config["native"]:
        if (not local.is_file() or not os.access(local, os.X_OK)
                or not local.resolve().is_relative_to(a.prefix.resolve() / "env")):
            raise RuntimeError("Required private venv Python is missing or unusable: " + str(local))
        python = str(local)
    else:
        # These profiles use only the host standard library. Do not silently
        # substitute this interpreter for a missing private-wheel environment.
        python = sys.executable
    args = [s.replace("{prefix}", str(a.prefix)).replace("{build}", str(a.build))
            for s in config["check_arguments"]]
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("PYTHONPATH", None)
    subprocess.run([python, "-I", "-B", str(a.recipe / "check.py"), *args],
                   env=environment, cwd=a.build, check=True)
    print(json.dumps({"status": "passed", "id": config["id"], "scope": config["scope"]}))


if __name__ == "__main__":
    main()
