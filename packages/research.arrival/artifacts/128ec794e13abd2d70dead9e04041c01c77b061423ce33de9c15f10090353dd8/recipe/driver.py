"""Create a fresh check output directory and run a frozen payload check."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", type=Path, required=True)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--recipe", type=Path, required=True)
    a = p.parse_args()
    if sys.flags.optimize:
        raise RuntimeError("Use Python without -O for reproducible validation")
    config = json.loads((a.recipe / "profile.json").read_text())
    a.build.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=config["id"].replace(".", "-") + "-", dir=a.build))
    argv = [sys.executable, "-B", str(a.recipe / "check.py")]
    for part in config["arguments"]:
        argv.append(part.replace("{prefix}", str(a.prefix)).replace("{work}", str(work)))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(argv, env=environment, cwd=work, check=False)
    if result.returncode:
        raise RuntimeError("Frozen profile failed; retained evidence: " + str(work))
    print(json.dumps({"status": "passed", "id": config["id"], "output": str(work),
                      "scope": config["scope"]}))


if __name__ == "__main__":
    main()
