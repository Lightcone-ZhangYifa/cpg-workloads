"""Prepare an independent Python/PaRSEC prefix from CPG's verified local inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("prefix", "source", "assets", "build", "recipe"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    config = json.loads((a.recipe / "resource.json").read_text())
    if sys.flags.optimize:
        raise RuntimeError("Use Python without optimization: upstream checkers retain assertions")
    if config["wheels"] and sys.version_info[:2] != (3, 12):
        raise RuntimeError("The supplied platform wheels require CPython 3.12")
    destination = a.prefix / "source"
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(a.source, destination, symlinks=True)
    for item in config.get("auxiliary_material", []):
        filename = Path(item["raw"]).name
        source = a.assets / "material" / filename
        if source.stat().st_size != item["bytes"] or hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Auxiliary source lock mismatch: " + filename)
        (a.prefix / "support-inputs").mkdir(exist_ok=True)
        shutil.copyfile(source, a.prefix / "support-inputs" / filename)
    # The source archive remains inside the CPG resource archive and the copied
    # tree is private to this prefix. Runtime/build dependencies are exact wheels.
    environment = dict(os.environ)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1",
                       PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_CACHE_DIR="1")
    if config["wheels"]:
        envdir = a.build / "build-env" if config["native"] else a.prefix / "env"
        venv.EnvBuilder(with_pip=True, symlinks=False).create(envdir)
        wheels = []
        for row in config["wheels"]:
            path = a.assets / "wheels" / row["filename"]
            if path.stat().st_size != row["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise RuntimeError("Wheel lock mismatch: " + row["filename"])
            wheels.append(str(path))
        subprocess.run([str(envdir / "bin/python"), "-I", "-B", "-m", "pip", "install",
                        "--no-index", "--no-deps", "--no-compile", "--disable-pip-version-check",
                        *wheels], env=environment, check=True)
    if config["native"]:
        environment["CPG_BUILD_JOBS"] = "1"
        subprocess.run(["bash", str(a.recipe / "build_parsec.sh"), str(destination),
                        str(a.build / "native-build"), str(a.prefix / "runtime"),
                        str(a.build / "build-env/bin/cmake")], env=environment, check=True)
    shutil.copyfile(a.recipe / "resource.json", a.prefix / "resource-profile.json")
    print(json.dumps({"status": "prepared", "id": config["id"], "offline": True}))


if __name__ == "__main__":
    main()
