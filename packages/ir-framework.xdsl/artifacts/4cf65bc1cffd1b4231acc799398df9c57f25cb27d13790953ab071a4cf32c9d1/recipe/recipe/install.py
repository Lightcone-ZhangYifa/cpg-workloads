#!/usr/bin/env python3
"""Offline installer for one locked worker-007 resource. No acquisition occurs here."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import venv
import zipfile


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unpack(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        members = source.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if Path(member.name).is_absolute() or ".." in parts or member.isdev():
                raise ValueError(f"unsafe archive entry: {member.name}")
        source.extractall(destination, filter="data")
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError("expected one root directory")
    return roots[0]


def wrapper(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(0o755)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", type=Path, required=True)
    ap.add_argument("--build-root", type=Path)
    ap.add_argument("--assets-root", type=Path, help="separately prepared source root; no network fallback")
    ap.add_argument("--libfirm-prefix", type=Path, help="consume the exact independently installed libFirm dependency")
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("--jobs must be positive")
    if sys.version_info < (3, 11):
        raise SystemExit("The offline recipe requires Python >=3.11 with tarfile data-filter support")
    here = Path(__file__).resolve().parent.parent
    lock = json.loads((here / "source-lock.json").read_text())
    assets_root = args.assets_root.resolve() if args.assets_root else here
    resource = lock["resource"]
    prefix = args.prefix.resolve()
    if resource in ("bril", "cparser", "libfirm") and (platform.system() != "Linux" or platform.machine() != "x86_64"):
        raise SystemExit("This packaged runtime/check target is Linux x86_64; no other target is claimed.")
    for item in lock["artifacts"]:
        path = assets_root / item["path"]
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise SystemExit(f"input hash/size mismatch: {item['path']}")
    if prefix.exists() and any(prefix.iterdir()):
        raise SystemExit(f"installation prefix is not empty: {prefix}")
    prefix.mkdir(parents=True, exist_ok=True)
    if args.build_root:
        build_parent = args.build_root.resolve()
        build_parent.mkdir(parents=True, exist_ok=True)
    else:
        build_parent = prefix.parent
    share = prefix / "share/cpg"
    share.mkdir(parents=True)
    shutil.copy2(here / "source-lock.json", share / "source-lock.json")
    shutil.copytree(here / "checks", share / "checks")
    shutil.copy2(here / "recipe/check.py", share / "check.py")
    evidence = share / "evidence"
    evidence.mkdir()
    commands = []
    started = time.monotonic()
    env = dict(os.environ)
    env.update(PYTHONNOUSERSITE="1", PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    def run(command, cwd=None, name="command"):
        log_path = evidence / (name + ".log")
        with log_path.open("w") as output:
            process = subprocess.run([str(x) for x in command], cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=900)
        commands.append({"argv": [str(x) for x in command], "exit_code": process.returncode, "log": log_path.name})
        if process.returncode:
            raise RuntimeError(f"{name} failed ({process.returncode}):\n{log_path.read_text()[-5000:]}")
    with tempfile.TemporaryDirectory(prefix="cpg-" + resource + "-build-", dir=build_parent) as directory:
        temporary = Path(directory)
        source_roots = {}
        for name, artifact in lock.get("source_archives", {}).items():
            extracted = unpack(assets_root / artifact, temporary / ("unpack-" + name))
            destination = share / "source" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(extracted, destination)
            source_roots[name] = destination
        if resource == "bril":
            extracted = unpack(assets_root / lock["deno_archive"], temporary / "deno")
            runtime = prefix / "runtime"
            runtime.mkdir()
            shutil.copy2(extracted / "deno", runtime / "deno")
            (runtime / "deno").chmod(0o755)
            shutil.copy2(assets_root / lock["deno_license"], runtime / "LICENSE.md")
            wrapper(prefix / "bin/brili", 'from pathlib import Path\nimport os\np = Path(__file__).resolve().parent.parent\nos.environ.setdefault("DENO_NO_UPDATE_CHECK", "1")\nos.environ.setdefault("DENO_DIR", str(Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "cpg/bril/e8b05b703acc9601addd6053294a3040863194cc"))\nos.execv(str(p / "runtime/deno"), [str(p / "runtime/deno"), "run", "--cached-only", "--deny-net", "--no-prompt", str(p / "share/cpg/source/bril/brili.ts"), *os.sys.argv[1:]])\n')
        elif resource == "xdsl":
            if sys.version_info < (3, 11):
                raise SystemExit("xDSL 0.74.0 requires Python >=3.11")
            venv.EnvBuilder(with_pip=True).create(prefix / "venv")
            run([prefix / "venv/bin/python", "-m", "pip", "install", "--no-index", "--require-hashes", "--find-links", assets_root / "assets", "-r", here / "requirements.lock"], name="wheel-install")
            wrapper(prefix / "bin/xdsl-opt", 'from pathlib import Path\nimport os\np = Path(__file__).resolve().parent.parent\nos.execv(str(p / "venv/bin/python"), [str(p / "venv/bin/python"), "-m", "xdsl.tools.xdsl_opt", *os.sys.argv[1:]])\n')
        elif resource in ("libfirm", "cparser"):
            for command in ("cc", "make", "ar", "perl", "python3"):
                if not shutil.which(command):
                    raise SystemExit(f"missing build prerequisite: {command}")
            # Zip-extract the pure-Python portion of locked upstream wheels.
            # MarkupSafe's documented ImportError fallback selects _native.py.
            # No CPython-specific extension is copied or silently loaded.
            deps = temporary / "python-build-deps"
            deps.mkdir()
            for wheel in lock["build_wheels"]:
                with zipfile.ZipFile(assets_root / wheel) as archive:
                    for name in archive.namelist():
                        path = Path(name)
                        if path.is_absolute() or ".." in path.parts:
                            raise ValueError("unsafe wheel member")
                        if name.endswith("/") or name.endswith((".so", ".pyd", ".dll")):
                            continue
                        destination = deps / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(name))
            env["PYTHONPATH"] = str(deps)
            # Make's env shebang must select the same interpreter as this recipe.
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            run([sys.executable, "-c", "import jinja2, markupsafe; print(jinja2.__version__); print(jinja2.__file__); print(markupsafe._escape_inner.__module__); assert markupsafe._escape_inner.__module__ == 'markupsafe._native'"], name="build-python-dependencies")
            staged = temporary / "build"
            staged.mkdir()
            libfirm = staged / "libfirm"
            shutil.copytree(source_roots["libfirm"], libfirm)
            (libfirm / "config.mak").write_text("REVISION = " + lock["pins"]["libfirm"] + "\n")
            flags = ["-j" + str(args.jobs), "variant=debug", "CFLAGS_debug=-O0 -g0"]
            if resource == "libfirm":
                run(["make", *flags], cwd=libfirm, name="libfirm-build")
                run(["make", *flags, "test"], cwd=libfirm, name="libfirm-upstream-tests")
                shutil.copytree(libfirm / "include/libfirm", prefix / "include/libfirm")
                shutil.copytree(libfirm / "build/gen/include/libfirm", prefix / "include/libfirm", dirs_exist_ok=True)
                (prefix / "lib").mkdir()
                for name in ("libfirm.a", "libfirm.so"):
                    shutil.copy2(libfirm / "build/debug" / name, prefix / "lib" / name)
                tests = prefix / "libexec/upstream-tests"
                tests.mkdir(parents=True)
                for test in sorted((libfirm / "build/debug").glob("*.exe")):
                    shutil.copy2(test, tests / test.name)
                pkgconfig = prefix / "lib/pkgconfig"
                pkgconfig.mkdir()
                (pkgconfig / "libfirm.pc").write_text("prefix=${pcfiledir}/../..\nlibdir=${prefix}/lib\nincludedir=${prefix}/include\n\nName: libFirm\nDescription: graph-based compiler IR and backend\nVersion: 1.22\nLibs: -L${libdir} -lfirm -lm\nCflags: -I${includedir}\n")
            else:
                cparser = staged / "cparser"
                shutil.copytree(source_roots["cparser"], cparser)
                configuration = "REVISION = " + lock["pins"]["cparser"] + "\nCOMPILER_INCLUDE_DIR =\n"
                if args.libfirm_prefix:
                    dependency = args.libfirm_prefix.resolve()
                    dependency_lock = json.loads((dependency / "share/cpg/source-lock.json").read_text())
                    if dependency_lock.get("resource") != "libfirm" or dependency_lock["pins"]["libfirm"] != lock["pins"]["libfirm"]:
                        raise ValueError("cparser libFirm dependency pin mismatch")
                    dependency_library = dependency / "lib/libfirm.a"
                    configuration += "FIRM_CPPFLAGS = -I" + str(dependency / "include") + " -I" + str(dependency / "include/libfirm") + "\nFIRM_LIBS = " + str(dependency_library) + " -lm\nLIBFIRM_FILE =\nLIBFIRM_FILE_DLL =\n"
                    (evidence / "libfirm-dependency.json").write_text(json.dumps({"prefix": str(dependency), "commit": dependency_lock["pins"]["libfirm"], "library_sha256": sha256(dependency_library), "consumption": "headers and static library used in actual cparser compile/link"}, indent=2) + "\n")
                else:
                    (cparser / "libfirm").mkdir(exist_ok=True)
                    configuration += "FIRM_HOME = " + str(libfirm) + "\n"
                (cparser / "config.mak").write_text(configuration)
                run(["make", *flags], cwd=cparser, name="cparser-with-libfirm-build")
                (prefix / "libexec").mkdir()
                shutil.copy2(cparser / "build/debug/cparser", prefix / "libexec/cparser-real")
                shutil.copytree(cparser / "include", prefix / "share/cparser/include")
                wrapper(prefix / "bin/cparser", 'from pathlib import Path\nimport os\np = Path(__file__).resolve().parent.parent\nos.execv(str(p / "libexec/cparser-real"), [str(p / "libexec/cparser-real"), "-isystem", str(p / "share/cparser/include"), *os.sys.argv[1:]])\n')
        else:
            raise SystemExit(f"unsupported manifest resource: {resource}")
    wrapper(prefix / "bin/cpg-check", 'from pathlib import Path\nimport os\np = Path(__file__).resolve().parent.parent\nos.execv(os.sys.executable, [os.sys.executable, str(p / "share/cpg/check.py"), "--prefix", str(p), *os.sys.argv[1:]])\n')
    report = {"resource": resource, "status": "installed", "downloaded_during_install": False,
              "source_and_build_trees_independent": True, "commands": commands,
              "python_executable": sys.executable, "platform": platform.platform(),
              "elapsed_seconds": time.monotonic() - started, "artifact_sha256": {x["path"]: x["sha256"] for x in lock["artifacts"]},
              "functional_check": "separate recipe/check.py action required"}
    (evidence / "install.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"resource": resource, "status": "installed", "prefix": str(prefix), "evidence": str(evidence / "install.json")}))


if __name__ == "__main__":
    main()
