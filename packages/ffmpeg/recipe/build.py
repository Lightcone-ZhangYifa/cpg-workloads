#!/usr/bin/env python3
"""Build the explicit portable FFmpeg profile and run its actual FATE suite."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import traceback


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    source, build, prefix = (getattr(args, x).resolve() for x in ("source", "build", "prefix"))
    obj, logs = build / "obj", build / "build-evidence"
    obj.mkdir(parents=True, exist_ok=False)
    logs.mkdir(parents=True, exist_ok=False)
    config = json.loads((Path(__file__).parent / "config.json").read_text())
    report = {"schema_version": 1, "resource": "ffmpeg", "status": "running", "commands": [],
              "configuration": config, "patches": [], "upstream_tests": {"status": "not_run"},
              "original_source": str(source), "source_mutation": "none"}
    environment = dict(os.environ)
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "CPATH", "LIBRARY_PATH", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "PKG_CONFIG_PATH"):
        environment.pop(name, None)
    environment.update(PATH="/usr/bin:/bin", LC_ALL="C")

    def run(label, argv, timeout=1800):
        argv = [str(x) for x in argv]
        with (logs / (label + ".stdout")).open("wb") as out, (logs / (label + ".stderr")).open("wb") as err:
            result = subprocess.run(argv, cwd=obj, env=environment, stdout=out, stderr=err, timeout=timeout)
        report["commands"].append({"label": label, "argv": argv, "cwd": str(obj), "returncode": result.returncode,
                                   "stdout": label + ".stdout", "stderr": label + ".stderr"})
        (logs / "build-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if result.returncode:
            raise RuntimeError("Build command failed: " + label)
        return (logs / (label + ".stdout")).read_text(errors="replace")

    try:
        run("configure", ["/bin/sh", source / "configure", "--prefix=" + str(prefix), *config["configure_options"]])
        run("make", ["/usr/bin/make", "-j" + str(min(2, max(1, args.jobs)))])
        listed = run("fate-list", ["/usr/bin/make", "fate-list"])
        declared = sorted(set(re.findall(r"^fate-([A-Za-z0-9_.+-]+)\s*$", listed, re.MULTILINE)))
        if not declared:
            raise AssertionError("The selected FATE suite enumerated no tests")
        hardware_listing = run("fate-hardware-list", ["/usr/bin/make", "--no-print-directory",
            "--eval=cpg-fate-hardware-list: ; @printf '%s\\n' $(sort $(FATE_HW-yes))", "cpg-fate-hardware-list"])
        hardware = sorted(set(re.findall(r"^fate-([A-Za-z0-9_.+-]+)\s*$", hardware_listing, re.MULTILINE)))
        # Upstream tests/Makefile adds FATE_HW-yes to fate-list after assigning
        # the default fate prerequisites. Those tests require explicit fate-hw.
        selected = sorted(set(declared) - set(hardware))
        run("fate", ["/usr/bin/make", "-j" + str(min(2, max(1, args.jobs))), "fate"], timeout=1800)
        report_files = sorted((obj / "tests/data/fate").glob("*.rep"))
        reports = []
        for path in report_files:
            line = path.read_text().strip().splitlines()
            if len(line) != 1:
                raise AssertionError("Unexpected FATE result format: " + path.name)
            values = line[0].split(":")
            if len(values) < 2:
                raise AssertionError("Malformed FATE report: " + path.name)
            reports.append({"test": path.stem, "result": values[1], "report": path.name, "sha256": sha(path)})
        executed = sorted(row["test"] for row in reports)
        if executed != selected or not reports or any(row["result"] != "0" for row in reports):
            raise AssertionError("FATE report set/result does not match the actual selected test list")
        report["upstream_tests"] = {"status": "passed", "suite": "FFmpeg FATE selected native profile, no external sample corpus",
                                    "listed_total": len(declared), "selected_default_fate": len(selected),
                                    "hardware_not_selected": hardware, "executed": len(executed), "passed": len(reports),
                                    "failed": 0, "tests": reports,
                                    "excluded_scope": "External sample FATE corpus, disabled codecs, external libraries and assembly backends"}
        shutil.copytree(obj / "tests/data/fate", logs / "fate-results")
        for name in ("config.h", "config_components.h", "ffbuild/config.mak", "ffbuild/config.log"):
            path = obj / name
            if path.is_file():
                shutil.copy2(path, logs / name.replace("/", "-"))
        run("install", ["/usr/bin/make", "install"])
        for pc in sorted((prefix / "lib/pkgconfig").glob("*.pc")):
            original = pc.read_bytes()
            changed = re.sub(rb"(?m)^prefix=.*$", b"prefix=${pcfiledir}/../..", original)
            if changed == original:
                raise AssertionError("Cannot identify the installed pkg-config prefix")
            pc.write_bytes(changed)
            report["patches"].append({"scope": "installed pkg-config metadata only", "path": pc.relative_to(prefix).as_posix(),
                                      "before_sha256": hashlib.sha256(original).hexdigest(), "after_sha256": sha(pc),
                                      "operation": "Replace build-specific prefix with ${pcfiledir}/../.."})
        material = prefix / "share/ffmpeg/source"
        shutil.copytree(source, material, symlinks=True)
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        raise
    finally:
        (logs / "build-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if report["status"] == "passed":
            evidence = prefix / "share/compiler-playground/ffmpeg"
            evidence.mkdir(parents=True, exist_ok=True)
            shutil.copytree(logs, evidence / "build-evidence")
            (evidence / "profile.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
