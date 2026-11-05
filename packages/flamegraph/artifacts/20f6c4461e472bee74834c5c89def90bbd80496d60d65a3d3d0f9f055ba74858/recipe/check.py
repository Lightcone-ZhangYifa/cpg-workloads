#!/usr/bin/env python3
"""Exercise the pinned FlameGraph scripts with explicit weighted stack fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


EXPECTED = {"probe;root;main;parse": 300, "probe;root;main;optimize": 200,
            "probe;root;main;emit": 100}
AFTER = {**EXPECTED, "probe;root;main;parse": 200, "probe;root;main;optimize": 300}
SVG = "{http://www.w3.org/2000/svg}"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def folded_values(text, columns=1):
    values = {}
    for line in text.splitlines():
        parts = line.rsplit(" ", columns)
        if len(parts) != columns + 1 or parts[0] in values:
            raise ValueError("Missing columns or duplicate folded stack")
        numbers = tuple(int(value) for value in parts[1:])
        if any(value < 0 for value in numbers):
            raise ValueError("A folded weight is negative")
        values[parts[0]] = numbers[0] if columns == 1 else numbers
    return values


def validate_folded(text):
    values = folded_values(text)
    if values != EXPECTED:
        raise ValueError("Collapsed stacks lost the declared paths or event-period weights")
    return values


def validate_svg(text, *, differential=False):
    root = ET.fromstring(text)
    if root.tag != SVG + "svg":
        raise ValueError("The renderer did not emit an SVG document")
    titles = [node.text for node in root.iter(SVG + "title")]
    expected = ["all (600 weight, 100%)"]
    if differential:
        expected += ["parse (200 weight, 33.33%; -16.67%)",
                     "optimize (300 weight, 50.00%; +16.67%)",
                     "emit (100 weight, 16.67%; 0.00%)"]
    else:
        expected += ["parse (300 weight, 50.00%)", "optimize (200 weight, 33.33%)",
                     "emit (100 weight, 16.67%)"]
    for title in expected:
        if titles.count(title) != 1:
            raise ValueError("Missing, duplicated or incorrect SVG frame: " + title)
    frames = 0
    for group in root.iter(SVG + "g"):
        title = group.find(SVG + "title")
        if title is None:
            continue
        rectangle = group.find(SVG + "rect")
        if rectangle is None:
            raise ValueError("A titled SVG frame has no rectangle")
        width = float(rectangle.attrib["width"])
        if not math.isfinite(width) or width <= 0:
            raise ValueError("An SVG frame has nonpositive or nonfinite width")
        frames += 1
    if frames != 7:
        raise ValueError("The SVG does not contain exactly the seven fixture frames")
    return {"frames": frames, "required_titles": expected}


def verify_scripts(prefix, expected_version):
    locks = json.loads(Path(__file__).with_name("script-locks.json").read_text())
    actual_version = "commit-" + locks["commit"][:12]
    if actual_version != expected_version:
        raise ValueError("The declared commit and script identity file differ")
    identities = {}
    for name, lock in locks["scripts"].items():
        path = prefix / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != lock["bytes"] or digest(path) != lock["sha256"]:
            raise ValueError("The installed pinned script differs: " + name)
        identities[name] = lock
    return {"version": actual_version, "commit": locks["commit"], "scripts": identities,
            "original_source_sha256": locks["source_sha256"]}


def qualify(args, directory, evidence):
    identity = verify_scripts(args.prefix, args.expected_version)
    if args.identity_only:
        return {"status": "passed", "check": "pinned-script-identities", **identity, **evidence}
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PERL5OPT", "PERL5LIB", "PERLLIB"}}
    environment["LC_ALL"] = "C"
    launcher = [str(args.perl)]
    if args.loader:
        if not args.library_path:
            raise ValueError("A private loader requires a matching library path")
        launcher = [str(args.loader), "--library-path", args.library_path, str(args.perl)]
    launcher += ["-f"]
    bootstrap = None
    if args.perl_include:
        if args.private_root is None:
            raise ValueError("Private module paths require their private root")
        root = args.private_root.resolve()
        for include in args.perl_include:
            if not include.is_dir() or not include.resolve().is_relative_to(root):
                raise ValueError("A private Perl module directory is outside its root")
        bootstrap = directory / "bootstrap" / "CPGPrivatePerl.pm"
        bootstrap.parent.mkdir()
        quoted = ["'" + str(path.resolve()).replace("\\", "\\\\").replace("'", "\\'") + "'"
                  for path in args.perl_include]
        bootstrap.write_text("BEGIN { @INC = (" + ", ".join(quoted) + "); }\n1;\n")
        launcher += ["-I" + str(bootstrap.parent), "-MCPGPrivatePerl"]
        evidence["private_module_policy"] = {"ambient_module_fallback": False,
            "include_directories": [str(path.resolve()) for path in args.perl_include],
            "bootstrap_sha256": digest(bootstrap)}
    commands = evidence.setdefault("commands", [])

    def run(arguments, *, data=None, expected=0, output=None):
        command = launcher + [str(value) for value in arguments]
        result = subprocess.run(command, input=data, capture_output=True, text=True,
                                env=environment, timeout=30, check=False)
        commands.append({"argv": command, "stdin": data, "returncode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        if output:
            (directory / output).write_text(result.stdout)
        if result.returncode != expected:
            raise ValueError(f"Perl script returned {result.returncode}, expected {expected}")
        return result

    audit_code = ('use strict; use Getopt::Long; use Getopt::Std; use open qw(:std :utf8); '
                  'use JSON::PP; print JSON::PP->new->canonical->encode({version=>"$^V", modules=>\\%INC});')
    perl = json.loads(run(["-e", audit_code]).stdout)
    if args.expected_perl_version and perl["version"] != "v" + args.expected_perl_version:
        raise ValueError("The private Perl upstream version differs")
    if args.perl_include:
        for name, value in perl["modules"].items():
            path = Path(value)
            if name == "CPGPrivatePerl.pm":
                if path.resolve() != bootstrap.resolve():
                    raise ValueError("The explicit Perl bootstrap identity differs")
            elif not path.is_absolute() or not path.resolve().is_relative_to(args.private_root.resolve()):
                raise ValueError("A Perl module escaped the exact private closure: " + name)
        perl["module_sha256"] = {name: digest(value) for name, value in perl["modules"].items()}
    evidence["perl"] = perl
    for script in identity["scripts"]:
        syntax = run(["-c", args.prefix / script])
        if "syntax OK" not in syntax.stderr:
            raise ValueError("The syntax probe did not report success for " + script)
    if args.syntax_only:
        return {"status": "passed", "check": "perl-syntax", **identity, **evidence}

    perf_text = "".join(f"probe 123 1.{number:06d}: {weight} cycles:\n"
                        f"        3 {stack.rsplit(';', 1)[1]} (/tmp/probe)\n"
                        "        2 main (/tmp/probe)\n        1 root (/tmp/probe)\n\n"
                        for number, (stack, weight) in enumerate(EXPECTED.items(), 1))
    (directory / "synthetic.perf.txt").write_text(perf_text)
    collapsed = run([args.prefix / "stackcollapse-perf.pl"], data=perf_text, output="before.folded")
    folded = validate_folded(collapsed.stdout)
    normal = run([args.prefix / "flamegraph.pl", "--hash", "--countname", "weight",
                  "--title", "Synthetic weighted stacks"], data=collapsed.stdout, output="flamegraph.svg")
    normal_frames = validate_svg(normal.stdout)
    after_text = "".join(f"{stack} {weight}\n" for stack, weight in AFTER.items())
    (directory / "after.folded").write_text(after_text)
    differential = run([args.prefix / "difffolded.pl", directory / "before.folded", directory / "after.folded"],
                       output="differential.folded")
    expected_pairs = {stack: (weight, AFTER[stack]) for stack, weight in EXPECTED.items()}
    if folded_values(differential.stdout, columns=2) != expected_pairs:
        raise ValueError("Differential folding lost the before/after pair")
    rendered = run([args.prefix / "flamegraph.pl", "--hash", "--countname", "weight",
                    "--title", "Synthetic weighted difference"], data=differential.stdout, output="differential.svg")
    diff_frames = validate_svg(rendered.stdout, differential=True)
    invalid = run([args.prefix / "flamegraph.pl", "--countname", "weight"],
                  data="this is not a folded stack\n", expected=2, output="invalid-input.svg")
    if "ERROR: No stack counts found" not in invalid.stderr or "all (" in invalid.stdout:
        raise ValueError("Invalid input did not produce the declared failure diagnostic")
    ET.fromstring(invalid.stdout)
    evidence["files"] = {path.relative_to(directory).as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
                         for path in sorted(directory.rglob("*")) if path.is_file()}
    return {"status": "passed", "check": "fold-collapse-svg-differential-and-errors", **identity, **evidence,
            "weighted_stacks": folded, "normal_svg": normal_frames, "differential_svg": diff_frames,
            "synthetic_event_records": 3, "total_declared_event_weight": 600,
            "scope": "Synthetic perf-script records with explicit period weights; real upstream conversion/rendering. No profile capture, PMU measurement or benchmark score."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--perl", type=Path, default=Path("/usr/bin/perl"))
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--library-path")
    parser.add_argument("--perl-include", type=Path, action="append", default=[])
    parser.add_argument("--private-root", type=Path)
    parser.add_argument("--expected-perl-version")
    parser.add_argument("--output-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--identity-only", action="store_true")
    mode.add_argument("--syntax-only", action="store_true")
    args = parser.parse_args()
    args.prefix = args.prefix.resolve()
    evidence = {}
    try:
        if args.output_dir:
            directory = args.output_dir.resolve()
            directory.mkdir(parents=True, exist_ok=False)
            result = qualify(args, directory, evidence)
        else:
            with tempfile.TemporaryDirectory(prefix="cpg-flamegraph-check-") as temporary:
                result = qualify(args, Path(temporary), evidence)
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__, "reason": str(error), **evidence}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
