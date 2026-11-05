#!/usr/bin/env python3
"""Build the portable generic BLIS profile and execute upstream BLAS/BLIS tests."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "build", "prefix"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    evidence = args.prefix / "share/compiler-playground/blis"
    evidence.mkdir(parents=True)
    args.build.mkdir(exist_ok=True)
    environment = dict(os.environ, CC="/usr/bin/gcc", CXX="/usr/bin/g++", BLIS_NUM_THREADS="1", OMP_NUM_THREADS="1", LC_ALL="C")
    for key in ("BLIS_JC_NT", "BLIS_PC_NT", "BLIS_IC_NT", "BLIS_JR_NT", "BLIS_IR_NT", "LD_PRELOAD", "CFLAGS", "LDFLAGS"):
        environment.pop(key, None)
    commands = []

    def run(label, argv):
        command = [str(x) for x in argv]
        print(json.dumps({"label": label, "argv": command}), flush=True)
        with (evidence / (label + ".stdout")).open("wb") as stdout, (evidence / (label + ".stderr")).open("wb") as stderr:
            completed = subprocess.run(command, cwd=args.build, env=environment, stdout=stdout, stderr=stderr)
        commands.append({"label": label, "argv": command, "returncode": completed.returncode})
        (evidence / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if completed.returncode:
            raise RuntimeError("Build or upstream test command failed: " + label)

    run("configure", [args.source / "configure", "--prefix=" + str(args.prefix), "--enable-cblas", "--enable-blas",
        "--enable-threading=pthreads", "--enable-shared", "--enable-static", "--blas-int-size=32", "generic"])
    run("build", ["/usr/bin/make", "-j" + str(args.jobs)])
    run("upstream-blis", ["/usr/bin/make", "-j" + str(args.jobs), "testsuite-run-fast"])
    # Upstream make check deliberately ignores its validation script exit code.
    # Execute that original script directly and validate nonempty result rows.
    run("upstream-blis-check", ["/bin/sh", args.source / "testsuite/check-blistest.sh", "output.testsuite"])
    tests = (args.build / "output.testsuite").read_text()
    rows = [line for line in tests.splitlines() if re.search(r"\bPASS\b", line)]
    if len(rows) < 100 or "FAILURE" in tests or "Exiting normally" not in tests:
        raise RuntimeError("The upstream BLIS numerical suite is incomplete or failed")
    shutil.copy2(args.build / "output.testsuite", evidence / "upstream-blis-output.txt")
    run("upstream-blas", ["/usr/bin/make", "-j" + str(args.jobs), "blastest-run"])
    run("upstream-blas-check", ["/bin/sh", args.source / "blastest/check-blastest.sh"])
    expected = {"out." + datatype + "blat" + str(level) for datatype in "sdcz" for level in (1, 2, 3)}
    observed = {p.name for p in args.build.glob("out.*")}
    if observed != expected:
        raise RuntimeError("Missing or unexpected upstream BLAS driver output")
    blas_counts = {}
    for name in sorted(expected):
        content = (args.build / name).read_text()
        passes = len(re.findall(r"\bPASS(?:ED)?\b", content, flags=re.I))
        if passes == 0 or "****" in content:
            raise RuntimeError("An upstream BLAS output is empty or contains a failure: " + name)
        blas_counts[name] = passes
        shutil.copy2(args.build / name, evidence / name)
    run("install", ["/usr/bin/make", "install"])
    # The package keeps all original build-system metadata; .pc paths are
    # explicitly made relative to permit independent installation prefixes.
    for path in (args.prefix / "share/pkgconfig").glob("*.pc"):
        lines = path.read_text().splitlines()
        for key, relative in (("prefix", "${pcfiledir}/../.."), ("exec_prefix", "${prefix}"),
                              ("libdir", "${prefix}/lib"), ("includedir", "${prefix}/include")):
            indices = [i for i,line in enumerate(lines) if line.startswith(key + "=")]
            if len(indices) != 1:
                raise RuntimeError("Missing or ambiguous pkg-config variable: " + key)
            lines[indices[0]] = key + "=" + relative
        path.write_text("\n".join(lines) + "\n")
        destination = args.prefix / "lib/pkgconfig" / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    destination = args.prefix / "libexec/blis"
    destination.mkdir(parents=True)
    shutil.copy2(args.build / "test_libblis.x", destination / "test_libblis.x")
    shutil.copytree(args.source, args.prefix / "share/blis/source")
    for name in ("build.py", "check.py", "api.c"):
        shutil.copy2(Path(__file__).with_name(name), evidence / name)
    (evidence / "profile.json").write_text(json.dumps({
        "id": "blis", "version": "2.1", "configuration": "generic", "blas_integer_bits": 32,
        "shared": True, "static": True, "cblas": True, "blas": True, "threading": "pthreads,single",
        "source_modified": False, "upstream_blis_pass_rows": len(rows), "upstream_blas_pass_markers": blas_counts,
        "upstream_threads": 1, "unperformed": ["architecture-tuned assembly configurations", "OpenMP/HPX",
            "full-size/mixed-domain/application-threaded upstream matrices", "cross-platform and performance qualification"]
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
