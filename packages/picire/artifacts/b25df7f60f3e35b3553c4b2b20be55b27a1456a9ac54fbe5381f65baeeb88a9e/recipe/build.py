#!/usr/bin/env python3
"""Build Picire into an independent venv using only locked local wheel inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def inventory(root):
    return [{"path": p.relative_to(root).as_posix(), "sha256": digest(p),
             "bytes": p.stat().st_size, "mode": p.stat().st_mode & 0o777}
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "assets", "prefix", "build"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    recipe = Path(__file__).resolve().parent
    source, prefix, build = args.source.resolve(), args.prefix.resolve(), args.build.resolve()
    need(sys.version_info[:2] == (3, 12), "This private wheel closure requires CPython 3.12")
    share = prefix / "share/picire"
    share.mkdir(parents=True)
    original = inventory(source)
    need(original, "Original Picire source is empty")
    shutil.copytree(source, share / "source", symlinks=True)
    need(inventory(share / "source") == original, "Original source copy changed")
    closure = json.loads((recipe / "closure.json").read_text())
    wheelhouse = share / "wheels"
    wheelhouse.mkdir()
    wheels, versions = [], {}
    for row in closure["distributions"]:
        declared = row["source"]
        filename = Path(declared["material_path"]).name
        src = recipe / "vendor" / filename
        need(src.is_file() and not src.is_symlink() and src.stat().st_size == declared["bytes"]
             and digest(src) == declared["sha256"], "Locked private wheel changed: " + filename)
        dst = wheelhouse / filename
        shutil.copy2(src, dst)
        wheels.append(dst)
        versions[row["distribution"]] = row["version"]
    patch = json.loads((recipe / "compatibility-patch.json").read_text())
    copied = build / "picire-build-source"
    shutil.copytree(source, copied, symlinks=True)
    for row in patch["files"]:
        path = copied / row["path"]
        need(digest(path) == row["original_sha256"], "Compatibility patch original identity differs")
        content = path.read_text()
        for replacement in row["replacements"]:
            need(content.count(replacement["before"]) == 1, "Compatibility replacement is not unique")
            content = content.replace(replacement["before"], replacement["after"])
        path.write_text(content)
        need(digest(path) == row["result_sha256"], "Compatibility patch result identity differs")
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(name, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull,
                       PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", SOURCE_DATE_EPOCH="315532800",
                       SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PICIRE="21.8", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    logs = build / "picire-install-logs"
    logs.mkdir()
    steps = []

    def run(argv, name):
        result = subprocess.run([str(x) for x in argv], cwd=build, env=environment,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
        (logs / (name + ".stdout")).write_bytes(result.stdout)
        (logs / (name + ".stderr")).write_bytes(result.stderr)
        steps.append({"name": name, "argv": [str(x) for x in argv], "returncode": result.returncode})
        save(logs / "steps.json", steps)
        need(result.returncode == 0, "Private installation step failed: " + name)
        return result

    runtime = prefix / "runtime"
    run([sys.executable, "-m", "venv", "--without-pip", "--copies", runtime], "create-private-venv")
    python = runtime / "bin/python"
    bootstrap = next(p for p in wheels if p.name.startswith("pip-"))
    code = "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('pip',run_name='__main__')"
    run([python, "-I", "-c", code, bootstrap, "install", "--no-index", "--no-deps", "--no-compile",
         "--disable-pip-version-check", *wheels], "install-locked-private-closure")
    built = build / "built-wheel"
    built.mkdir()
    run([python, "-I", "-m", "pip", "wheel", "--no-index", "--no-deps", "--no-build-isolation",
         "--wheel-dir", built, copied], "build-patched-copy-offline")
    candidates = list(built.glob("picire-21.8-py3-none-any.whl"))
    need(len(candidates) == 1 and len(list(built.iterdir())) == 1, "Offline build did not produce exactly Picire 21.8")
    installed_wheel = share / candidates[0].name
    shutil.copy2(candidates[0], installed_wheel)
    run([python, "-I", "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile", installed_wheel],
        "install-picire-wheel-offline")
    run([python, "-I", "-m", "pip", "check"], "validate-private-dependencies")
    (prefix / "bin").mkdir()
    launcher = prefix / "bin/picire"
    launcher.write_text('#!/bin/sh\nroot=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexec "$root/runtime/bin/python" -I -m picire "$@"\n')
    launcher.chmod(0o755)
    for name in ("check.py", "closure.json", "compatibility-patch.json"):
        shutil.copy2(recipe / name, share / name)
    versions["picire"] = "21.8"
    inspect = "import json,sys,importlib.metadata as m; print(json.dumps({'executable':sys.executable,'base_executable':sys._base_executable,'version':sys.version,'base_prefix':sys.base_prefix,'distributions':{d.metadata['Name']:d.version for d in m.distributions()}},sort_keys=True))"
    actual = json.loads(run([python, "-I", "-c", inspect], "installed-interpreter-and-distributions").stdout)
    normalize = lambda name: name.lower().replace("_", "-").replace(".", "-")
    need({normalize(k): v for k, v in actual["distributions"].items()} == {normalize(k): v for k, v in versions.items()},
         "Installed private environment differs from the exact distribution closure")
    profile = {"schema_version": 1, "resource_id": "picire", "version": "21.8", "original_source_files": original,
               "compatibility_patch": patch, "distributions": versions, "interpreter": actual,
               "interpreter_binary_sha256": digest(python), "base_interpreter_sha256": digest(actual["base_executable"]),
               "built_wheel": {"file": installed_wheel.name, "sha256": digest(installed_wheel), "bytes": installed_wheel.stat().st_size},
               "source_rebuild_required": True}
    # The runtime path is installation-local and deliberately not a relocatable binary contract.
    save(share / "profile.json", profile)
    print(json.dumps({"status": "passed", "private_distributions": len(versions), "original_files": len(original),
                      "built_wheel_sha256": profile["built_wheel"]["sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
