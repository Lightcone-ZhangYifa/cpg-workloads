#!/usr/bin/env python3
"""Build the locked Megaparsec source profile without acquiring network inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time


RESOURCE = "megaparsec"
VERSION = "9.8.3"
PRIMARY = "megaparsec-9.8.3.tar.gz"
GHC = "ghc-9.6.7-x86_64-ubuntu22_04-linux.tar.xz"
CABAL = "cabal-install-3.12.1.0-x86_64-linux-ubuntu22_04.tar.xz"
FRONTEND = "cpg-megaparsec-frontend"
FRONTEND_TARGET = FRONTEND + ":exe:" + FRONTEND
TEST_TARGET = "megaparsec-tests:test:tests"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def snapshot(root: Path) -> list[dict]:
    result = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        row = {"path": path.relative_to(root).as_posix(), "mode": stat.S_IMODE(info.st_mode)}
        if path.is_symlink():
            row.update(kind="symlink", target=os.readlink(path))
        elif path.is_file():
            row.update(kind="file", bytes=info.st_size, sha256=digest(path))
        elif path.is_dir():
            row.update(kind="directory")
        else:
            raise ValueError("Unsupported file in the source tree: " + str(path))
        result.append(row)
    return result


def ordinary(path: Path, *, directory=False) -> Path:
    path = path.expanduser()
    if ".." in path.parts:
        raise ValueError("An input/output path contains '..': " + str(path))
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("An input/output path traverses a symlink: " + str(path))
    if directory and not path.is_dir():
        raise ValueError("A required directory is absent: " + str(path))
    return path


def select_ghc_working_set(members: list[tarfile.TarInfo]) -> tuple[list[tarfile.TarInfo], dict]:
    """Keep the ordinary compiler closure, preserving every bundled notice."""
    selected, excluded = [], []
    reasons = {"documentation": {"members": 0, "bytes": 0},
               "profiling_library": {"members": 0, "bytes": 0},
               "profiling_interface": {"members": 0, "bytes": 0},
               "profiling_interpreter": {"members": 0, "bytes": 0}}
    for member in members:
        path = Path(member.name)
        name = path.name
        # Licenses under doc/ are retained for the redistributed binary notices.
        if name.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT")):
            selected.append(member)
            continue
        reason = None
        if len(path.parts) > 1 and path.parts[1] == "doc":
            reason = "documentation"
        elif name.endswith("_p.a"):
            reason = "profiling_library"
        elif name.endswith(".p_hi"):
            reason = "profiling_interface"
        elif name == "ghc-iserv-prof" or name.startswith("ghc-iserv-prof-"):
            reason = "profiling_interpreter"
        if reason is None:
            selected.append(member)
        else:
            size = member.size if member.isfile() else 0
            reasons[reason]["members"] += 1
            reasons[reason]["bytes"] += size
            excluded.append({"path": member.name, "bytes": size, "reason": reason})
    return selected, {"profile": "nonprofiling_compiler", "complete_original_raw_retained": True,
        "profiling_supported": False, "documentation_installed": False,
        "license_copying_copyright_members_retained": True,
        "selection_rules": ["Omit top-level doc/ except license notices", "Omit *_p.a", "Omit *.p_hi",
                            "Omit ghc-iserv-prof and ghc-iserv-prof-*"],
        "included_members": len(selected),
        "included_file_bytes": sum(m.size for m in selected if m.isfile()),
        "excluded_members": len(excluded), "excluded_file_bytes": sum(row["bytes"] for row in excluded),
        "excluded_by_reason": reasons, "excluded_inventory": excluded}


def extract(raw: Path, destination: Path, *, single_root: bool, ghc_profile: dict | None = None) -> Path:
    """Expand an exact local archive into a fresh, confined independent tree."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    with tarfile.open(raw, "r:*") as archive:
        members = archive.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                raise ValueError("An archive member is not a confined relative path")
        roots = {Path(member.name).parts[0] for member in members if Path(member.name).parts}
        if not members or not any(member.isfile() for member in members):
            raise ValueError("The input archive contains no ordinary files: " + str(raw))
        if single_root and len(roots) != 1:
            raise ValueError("Expected exactly one top-level source directory: " + str(raw))
        if ghc_profile is not None:
            if not single_root:
                raise ValueError("The GHC working profile requires one top-level directory")
            members, profile = select_ghc_working_set(members)
            ghc_profile.update(profile)
        archive.extractall(destination, members=members, filter="data")
    root = destination / next(iter(roots)) if single_root else destination
    ordinary(root, directory=True)
    if not root.resolve().is_relative_to(destination.resolve()):
        raise ValueError("The archive root leaves its extraction destination")
    return root


def copy_notices(source: Path, destination: Path) -> int:
    count = 0
    for path in sorted(source.rglob("*")):
        if not path.name.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT")) or not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(source.resolve()):
            raise ValueError("A license link leaves its input tree")
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, target)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--primary-archive", type=Path,
                        help="Exact primary archive for a direct recipe invocation; source packages resolve this internally.")
    parser.add_argument("--upstream-tests", action="store_true",
                        help="Also compile and run the original upstream test suite in this source operation.")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    source = ordinary(args.source, directory=True)
    build = ordinary(args.build, directory=True)
    prefix = ordinary(args.prefix, directory=True)
    present = list(prefix.iterdir())
    if present:
        marker = prefix / ".cpg-prefix.json"
        if len(present) != 1 or present[0] != marker or marker.is_symlink() or not marker.is_file():
            raise FileExistsError("The installation prefix contains preexisting content")
        owner = json.loads(marker.read_text(encoding="utf-8"))
        if (owner.get("kind") != "compiler_playground_prefix_ownership"
                or owner.get("schema_version") != 1 or owner.get("prefix") != str(prefix)):
            raise ValueError("The installation prefix has an invalid ownership marker")
    for first, second in ((source, build), (source, prefix), (build, prefix)):
        if first == second or first in second.parents or second in first.parents:
            raise ValueError("Source, build and installation roots must be independent")
    recipe = Path(__file__).absolute().parent
    evidence = build / "megaparsec-evidence"
    evidence.mkdir()
    receipt = {"schema_version": 1, "resource_id": RESOURCE, "version": VERSION,
               "status": "running", "network_acquisition": False,
               "offline_mechanism": "Only locked local package directories; Cabal offline and active-repositories=:none.",
               "network_boundary": "No OS-level network sandbox is claimed.",
               "ghc_scope": "Official prebuilt GHC 9.6.7, configured in an independent nonprofiling bindist working set; original raw remains complete. GHC is not source-built; profiling and documentation are not installed.",
               "paths": {"source": str(source), "build": str(build), "prefix": str(prefix)},
               "commands": []}
    source_before = snapshot(source)
    write_json(evidence / "original-source-before.json", source_before)
    environment = dict(os.environ)
    discarded = [name for name in environment if name.startswith("LD_") or name in {
        "GHC_PACKAGE_PATH", "GHC_ENVIRONMENT", "CABAL_CONFIG", "CABAL_DIR", "LIBRARY_PATH"}]
    for name in discarded:
        environment.pop(name, None)
    environment.update(LC_ALL="C.UTF-8", LANG="C.UTF-8", PYTHONDONTWRITEBYTECODE="1",
                       GHC_ENVIRONMENT="-", SOURCE_DATE_EPOCH="0")
    receipt["ignored_ambient_variable_names"] = sorted(discarded)

    def run(label: str, argv, *, cwd: Path, timeout=3600) -> str:
        command = [str(x) for x in argv]
        out, err = evidence / (label + ".stdout.log"), evidence / (label + ".stderr.log")
        row = {"label": label, "argv": command, "cwd": str(cwd),
               "stdout": out.name, "stderr": err.name}
        receipt["commands"].append(row)
        print(json.dumps({"phase": label, "argv": command}), flush=True)
        start = time.monotonic()
        try:
            with out.open("wb") as stdout, err.open("wb") as stderr:
                result = subprocess.run(command, cwd=cwd, env=environment,
                                        stdout=stdout, stderr=stderr, timeout=timeout, check=False)
            row["returncode"] = result.returncode
            if result.returncode:
                raise RuntimeError("Command failed: " + label + "; see " + str(err))
        except BaseException as error:
            row["error"] = str(error)
            raise
        finally:
            row["elapsed_seconds"] = time.monotonic() - start
            write_json(evidence / "build-receipt.json", receipt)
        return out.read_text(encoding="utf-8", errors="replace")

    try:
        lock_path = recipe / "input-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        rows = lock["sources"]
        by_name = {row["filename"]: row for row in rows}
        if len(by_name) != len(rows) or any(name not in by_name for name in (PRIMARY, GHC, CABAL)):
            raise ValueError("The complete, unique primary and toolchain input locks are required")
        receipt["input_lock_sha256"] = digest(lock_path)
        primary_raw = ordinary(args.primary_archive or recipe.parent / "sources" / by_name[PRIMARY]["sha256"])
        if (not primary_raw.is_file() or primary_raw.stat().st_size != by_name[PRIMARY]["bytes"]
                or digest(primary_raw) != by_name[PRIMARY]["sha256"]):
            raise ValueError("The primary archive differs from its exact input lock")
        reference = extract(primary_raw, build / "primary-reference", single_root=True)
        if snapshot(reference) != source_before:
            raise ValueError("The supplied source tree differs from the complete locked primary archive")
        receipt["primary_source_matches_original_archive"] = True
        for name, row in by_name.items():
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError("A raw filename is not a basename")
            if name == PRIMARY:
                continue
            raw = ordinary(recipe / "inputs" / name)
            if not raw.is_file() or raw.stat().st_size != row["bytes"] or digest(raw) != row["sha256"]:
                raise ValueError("A private source/build input differs from its lock: " + name)
        receipt["source_inputs"] = rows

        native = build / "native-lib"
        native.mkdir()
        system_libraries = []
        for number, library in enumerate(("libgmp.so.10", "libtinfo.so.6", "libffi.so.8"), 1):
            observed = run("native-library-" + str(number), ["gcc", "-print-file-name=" + library], cwd=build, timeout=30).strip()
            resolved = Path(observed).resolve(strict=True)
            if not resolved.is_file() or resolved.read_bytes()[:4] != b"\x7fELF":
                raise ValueError("A required native runtime is not an ELF file: " + library)
            system_libraries.append({"name": library, "path": str(resolved),
                                     "bytes": resolved.stat().st_size, "sha256": digest(resolved)})
            if library == "libgmp.so.10":
                (native / "libgmp.so").symlink_to(resolved)
        environment["LIBRARY_PATH"] = str(native)
        receipt["native_runtime_inputs"] = system_libraries
        receipt["native_link_alias"] = {"path": str(native / "libgmp.so"),
            "scope": "Private build-time linker alias to the observed system libgmp.so.10; no runtime library is bundled or replaced."}
        run("native-compiler-version", ["gcc", "--version"], cwd=build, timeout=30)

        tools = build / "toolchain"
        tools.mkdir()
        ghc_profile = {}
        ghc_root = extract(recipe / "inputs" / GHC, tools / "ghc", single_root=True, ghc_profile=ghc_profile)
        ghc_profile["original_raw_sha256"] = by_name[GHC]["sha256"]
        write_json(evidence / "ghc-working-set.json", ghc_profile)
        receipt["ghc_working_set"] = {key: value for key, value in ghc_profile.items() if key != "excluded_inventory"}
        receipt["ghc_working_set"]["selection_manifest_sha256"] = digest(evidence / "ghc-working-set.json")
        cabal_root = extract(recipe / "inputs" / CABAL, tools / "cabal", single_root=False)
        run("ghc-configure", [ghc_root / "configure", "--prefix=" + str(ghc_root)], cwd=ghc_root, timeout=300)
        # configure writes config.mk; this narrowly scoped target creates the
        # in-place compiler's settings without copying/installing the bindist.
        run("ghc-settings", ["make", "--no-print-directory", "lib/settings"], cwd=ghc_root, timeout=60)
        ghc, ghc_pkg, cabal = ghc_root / "bin/ghc", ghc_root / "bin/ghc-pkg", cabal_root / "cabal"
        environment["PATH"] = os.pathsep.join((str(ghc_root / "bin"), str(cabal_root), environment.get("PATH", os.defpath)))
        if run("ghc-version", [ghc, "--numeric-version"], cwd=build, timeout=30).strip() != "9.6.7":
            raise ValueError("The locked GHC did not report 9.6.7")
        if run("cabal-version", [cabal, "--numeric-version"], cwd=build, timeout=30).strip() != "3.12.1.0":
            raise ValueError("The locked Cabal did not report 3.12.1.0")
        ghc_libdir = Path(run("ghc-libdir", [ghc, "--print-libdir"], cwd=build, timeout=30).strip()).resolve()
        if not ghc_libdir.is_relative_to(ghc_root.resolve()) or not ghc_libdir.is_dir():
            raise ValueError("GHC uses a library directory outside its independent bindist")
        run("ghc-global-packages", [ghc_pkg, "--global", "--no-user-package-db", "list", "--simple-output"], cwd=build, timeout=30)
        receipt["toolchain"] = {"ghc": str(ghc), "cabal": str(cabal), "libdir": str(ghc_libdir),
                                "ghc_sha256": digest(ghc), "cabal_sha256": digest(cabal),
                                "installation_method": "independent_nonprofiling_in_place_bindist",
                                "settings_make_target": "lib/settings", "make_install_performed": False}

        project = build / "project"
        packages = project / "packages"
        packages.mkdir(parents=True)
        main_package = packages / "megaparsec-9.8.3"
        shutil.copytree(source, main_package)
        package_dirs = [main_package]
        for name in sorted(by_name):
            if name == PRIMARY or not name.endswith(".tar.gz"):
                continue
            package_dirs.append(extract(recipe / "inputs" / name, packages / name.removesuffix(".tar.gz"), single_root=True))
        frontend = project / "frontend"
        shutil.copytree(recipe / "frontend", frontend)
        package_dirs.append(frontend)
        entries = [p.relative_to(project).as_posix() for p in package_dirs]
        if not any((p / "megaparsec-tests.cabal").is_file() for p in package_dirs):
            raise ValueError("The locked upstream Megaparsec test package is absent")
        project_text = "packages:\n" + "\n".join("  " + item for item in entries) + "\n"
        project_text += ("active-repositories: :none\noffline: True\ntests: False\nbenchmarks: False\n"
                         "optimization: 1\nwrite-ghc-environment-files: never\n"
                         "package megaparsec-tests\n  tests: True\n")
        (project / "cabal.project").write_text(project_text, encoding="utf-8")
        cabal_home = build / "cabal-home"
        cabal_home.mkdir()
        config_path = project / "cabal.config"
        config = "active-repositories: :none\noffline: True\n"
        for key, relative in (("remote-repo-cache", "repository"), ("store-dir", "store"), ("logs-dir", "logs")):
            path = cabal_home / relative
            path.mkdir()
            config += key + ": " + str(path) + "\n"
        config += "world-file: " + str(cabal_home / "world") + "\n"
        config_path.write_text(config, encoding="utf-8")
        environment.update(CABAL_DIR=str(cabal_home), CABAL_CONFIG=str(config_path))
        common = [cabal, "--config-file=cabal.config"]
        compiler_flag = "--with-compiler=" + str(ghc)
        targets = [FRONTEND_TARGET]
        if args.upstream_tests:
            targets.append(TEST_TARGET)
        run("cabal-build", [*common, "v2-build", "--offline", compiler_flag,
                            "--jobs=" + str(args.jobs), *targets], cwd=project)
        receipt["upstream_tests"] = {"status": "not_run", "target": TEST_TARGET,
                                     "reason": "Ordinary source deployment compiles the library/frontend; use the separate offline upstream replay for the full test suite."}
        if args.upstream_tests:
            test_output = run("upstream-tests", [*common, "v2-test", "--offline", compiler_flag,
                                "--jobs=" + str(args.jobs), TEST_TARGET, "--test-show-details=direct",
                                "--test-option=--seed=20261101"], cwd=project)
            summaries = re.findall(r"(\d+) examples?, (\d+) failures?", test_output)
            if len(summaries) != 1 or int(summaries[0][0]) < 1 or int(summaries[0][1]) != 0:
                raise RuntimeError("A nonempty successful Hspec execution summary was not observed")
            receipt["upstream_tests"] = {"status": "passed", "target": TEST_TARGET, "seed": 20261101,
                                         "examples": int(summaries[0][0]), "failures": 0,
                                         "scope": "The original upstream test suite, using its ordinary property-test bounds; not exhaustive correctness."}
        executable_text = run("frontend-path", [*common, "list-bin", "--offline", compiler_flag, FRONTEND_TARGET], cwd=project, timeout=120)
        executable = Path(executable_text.strip()).resolve(strict=True)
        if not executable.is_relative_to(project.resolve()) or not executable.is_file():
            raise ValueError("The frontend artifact does not belong to this independent build")
        (prefix / "bin").mkdir()
        installed = prefix / "bin" / FRONTEND
        shutil.copy2(executable, installed)
        share = prefix / "share/compiler-playground/megaparsec"
        share.mkdir(parents=True)
        shutil.copytree(source, share / "upstream-source")
        shutil.copytree(recipe / "frontend", share / "frontend-source")
        shutil.copy2(recipe / "check_frontend.py", share / "check_frontend.py")
        shutil.copy2(recipe / "replay_upstream_tests.py", share / "replay_upstream_tests.py")
        shutil.copy2(recipe / "compile_client.py", share / "compile_client.py")
        shutil.copy2(recipe / "client_runtime.py", share / "client_runtime.py")
        shutil.copy2(lock_path, share / "input-lock.json")
        notices = prefix / "share/licenses/megaparsec"
        receipt["license_files"] = {}
        for package in package_dirs:
            receipt["license_files"][package.name] = copy_notices(package, notices / package.name)
        receipt["license_files"]["ghc"] = copy_notices(ghc_root, notices / "ghc")
        if not receipt["license_files"].get("megaparsec-9.8.3") or not receipt["license_files"].get("ghc"):
            raise ValueError("Primary library and GHC license notices were not found")
        run("frontend-version", [installed, "--version"], cwd=build, timeout=30)
        full_check = run("frontend-checks", [sys.executable, share / "check_frontend.py", "--binary", installed], cwd=build, timeout=180)
        checked = json.loads(full_check)
        if checked.get("status") != "passed" or checked.get("case_count", 0) < 1:
            raise RuntimeError("The installed frontend did not pass its independent nonempty checks")
        receipt["frontend_checks"] = {key: checked.get(key) for key in ("status", "mode", "case_count", "assertion_count")}
        receipt["installed_frontend_sha256"] = digest(installed)
        receipt["frontend_source_inventory"] = snapshot(recipe / "frontend")
        source_after = snapshot(source)
        write_json(evidence / "original-source-after.json", source_after)
        if source_after != source_before:
            raise ValueError("The preserved original Megaparsec source changed during the build")
        receipt["original_source_unchanged"] = True
        receipt["package_database_boundary"] = "Cabal's build database remains in this source operation; the installed prefix does not claim a relocatable GHC package database."
        receipt["project"] = str(project)
        receipt["project_files"] = {name: digest(project / name) for name in ("cabal.project", "cabal.config")}
        receipt["project_source_inventories"] = {p.relative_to(project).as_posix(): snapshot(p) for p in package_dirs}
        receipt["replay_environment"] = {name: environment[name] for name in (
            "CABAL_DIR", "CABAL_CONFIG", "GHC_ENVIRONMENT", "LIBRARY_PATH", "SOURCE_DATE_EPOCH", "LC_ALL", "LANG")}
        plan = project / "dist-newstyle/cache/plan.json"
        if not plan.is_file():
            raise ValueError("The actual Cabal build plan is absent")
        write_json(evidence / "build-receipt.json", receipt)
        shutil.copytree(evidence, share / "build-evidence")
        shutil.copy2(project / "cabal.project", share / "build-evidence/cabal.project")
        shutil.copy2(project / "cabal.config", share / "build-evidence/cabal.config")
        shutil.copy2(plan, share / "build-evidence/cabal-plan.json")
        receipt["status"] = "passed"
        write_json(evidence / "build-receipt.json", receipt)
        write_json(share / "build-evidence/build-receipt.json", receipt)
        print(json.dumps({"status": "passed", "resource_id": RESOURCE,
                          "upstream_examples": receipt["upstream_tests"].get("examples"),
                          "frontend_cases": checked["case_count"], "prefix": str(prefix)}), flush=True)
    except BaseException as error:
        receipt.update(status="failed", reason=str(error))
        write_json(evidence / "build-receipt.json", receipt)
        installed_receipt = prefix / "share/compiler-playground/megaparsec/build-evidence/build-receipt.json"
        if installed_receipt.is_file() and not installed_receipt.is_symlink():
            write_json(installed_receipt, receipt)
        raise


if __name__ == "__main__":
    main()
