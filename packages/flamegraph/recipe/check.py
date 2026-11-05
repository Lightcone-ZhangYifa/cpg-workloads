#!/usr/bin/env python3
"""Run the existing FlameGraph contracts against each installed private runtime."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--case", choices=["version", "functional"], required=True)
    args = parser.parse_args()
    prefix, recipe = args.prefix.resolve(strict=True), Path(__file__).resolve().parent
    args.build.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="flamegraph-" + args.case + "-", dir=args.build))
    result = {"schema_version": 1, "resource": "flamegraph", "case": args.case, "status": "failed", "commands": [], "evidence": str(work)}
    environment = {key: value for key, value in os.environ.items() if key not in {"PERL5LIB", "PERL5OPT", "PERLLIB", "LD_PRELOAD", "LD_LIBRARY_PATH"}}
    environment.update(LC_ALL="C", PYTHONDONTWRITEBYTECODE="1")

    def command(label, argv, data=None, expected=0):
        completed = subprocess.run(list(map(str, argv)), input=data, capture_output=True, text=True, env=environment, timeout=60)
        (work / (label + ".stdout")).write_text(completed.stdout)
        (work / (label + ".stderr")).write_text(completed.stderr)
        result["commands"].append({"label": label, "argv": list(map(str, argv)), "returncode": completed.returncode})
        save(work / "summary.json", result)
        need(completed.returncode == expected, "Unexpected result: " + label)
        return completed

    try:
        profile = json.loads((prefix / "share/flamegraph/profile.json").read_text())
        need(profile["resource_id"] == "flamegraph" and profile["version"] == args.expected_version, "Unexpected FlameGraph version")
        for row in profile["original_source_inventory"]:
            path = prefix / row["path"]
            need(path.is_file() and not path.is_symlink() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], "Original source changed")
        for row in profile["private_deb_inputs"]:
            path = prefix / "share/flamegraph/debs" / row["filename"]
            need(path.stat().st_size == row["bytes"] and sha(path) == row["sha256"], "Fixed Debian input changed")
        runtime, perl_profile = prefix / "share/flamegraph/runtime", profile["private_perl"]
        perl, loader = runtime / perl_profile["path"], runtime / perl_profile["loader"]
        need(sha(perl) == perl_profile["sha256"] and sha(loader) == perl_profile["loader_sha256"], "Private executable changed")
        library_path = ":".join(str(runtime / name) for name in perl_profile["library_directories"])
        resolution = command("private-libraries", [loader, "--library-path", library_path, "--list", perl])
        observed = []
        for line in resolution.stdout.splitlines():
            match = re.search(r"=> (/\S+)\s+\(", line)
            if match:
                path = Path(match.group(1)).resolve()
                need(path.is_relative_to(runtime), "A shared library escaped the private runtime")
                observed.append({"path": path.relative_to(runtime).as_posix(), "sha256": sha(path)})
        need(observed == perl_profile["resolved_libraries"], "Private dynamic library identity differs")
        arguments = ["/usr/bin/python3", recipe / "check_original.py", "--prefix", prefix, "--expected-version", args.expected_version,
            "--perl", perl, "--loader", loader, "--library-path", library_path, "--private-root", runtime,
            "--expected-perl-version", perl_profile["upstream_version"], "--output-dir", work / "original-contract"]
        for name in perl_profile["include_directories"]:
            arguments += ["--perl-include", runtime / name]
        if args.case == "version":
            arguments.append("--identity-only")
        original = command("original-contract", arguments)
        outcome = json.loads(original.stdout)
        need(outcome["status"] == "passed", "Original declared contract failed")
        result["original_contract"] = outcome
        perl_code = "use JSON::PP; print JSON::PP->new->canonical->encode({version=>qq($^V),modules=>\\%INC});"
        wrapper = json.loads(command("relative-perl", [prefix / "bin/flamegraph-perl", "-e", perl_code]).stdout)
        need(wrapper["version"] == "v5.38.2", "Installed launcher chose another Perl version")
        for name, value in wrapper["modules"].items():
            path = Path(value).resolve()
            need(path.is_relative_to(prefix / "share/flamegraph"), "A relative-launcher module escaped the private prefix")
        result["relative_launcher_modules"] = {name: {"path": str(Path(value).relative_to(prefix)), "sha256": sha(Path(value))} for name, value in wrapper["modules"].items()}
        if args.case == "functional":
            specification = importlib.util.spec_from_file_location("flamegraph_original_contract", recipe / "check_original.py")
            module = importlib.util.module_from_spec(specification)
            specification.loader.exec_module(module)
            original_dir = Path(outcome["evidence"]) if "evidence" in outcome else work / "original-contract"
            fixture_paths = list((work / "original-contract").rglob("synthetic.perf.txt"))
            need(len(fixture_paths) == 1, "Original functional fixture is ambiguous")
            fixtures = fixture_paths[0].parent
            collapsed = command("relative-collapse", [prefix / "bin/stackcollapse-perf"], data=(fixtures / "synthetic.perf.txt").read_text())
            need(module.validate_folded(collapsed.stdout) == module.EXPECTED, "Relative collapse changed weights")
            normal = command("relative-svg", [prefix / "bin/flamegraph", "--hash", "--countname", "weight"], data=collapsed.stdout)
            module.validate_svg(normal.stdout)
            differential = command("relative-difference", [prefix / "bin/difffolded", fixtures / "before.folded", fixtures / "after.folded"])
            need(module.folded_values(differential.stdout, columns=2) == {stack: (weight, module.AFTER[stack]) for stack, weight in module.EXPECTED.items()}, "Relative difference changed weights")
            svg = command("relative-differential-svg", [prefix / "bin/flamegraph", "--hash", "--countname", "weight"], data=differential.stdout)
            module.validate_svg(svg.stdout, differential=True)
            invalid = command("relative-invalid-input", [prefix / "bin/flamegraph"], data="this is not a folded stack\n", expected=2)
            need("ERROR: No stack counts found" in invalid.stderr, "Relative negative control missed its failure diagnostic")
            result["relative_functional_workflows"] = ["weighted-stack-collapse", "normal-svg", "differential-fold", "differential-svg"]
            result["negative_controls"] = ["original-invalid-folded-input", "relative-invalid-folded-input"]
        result.update(status="passed", original_source_files=len(profile["original_source_inventory"]), private_deb_packages=21,
                      machine_code_compilation="not_applicable", host_perl_used=False, host_apt_transaction="not_run",
                      scope="Real synthetic weighted-stack conversion/rendering and exact private-runtime relocation; no profile capture or hardware benchmark")
        save(work / "summary.json", result)
        print(json.dumps(result, sort_keys=True))
    except BaseException as error:
        result["error"] = type(error).__name__ + ": " + str(error)
        save(work / "summary.json", result)
        raise


if __name__ == "__main__":
    main()
