#!/usr/bin/env python3
"""Exercise installed generators and their produced programs without downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

UPSTREAM_TESTS = ("type_test", "data_test", "expr_test", "gen_test")


def checksum(resource, output):
    pattern = r"checksum = ([0-9a-fA-F]+)\s*" if resource == "csmith" else r"([0-9]+)\s*"
    match = re.fullmatch(pattern, output)
    if match is None:
        raise RuntimeError("Execution did not return exactly one valid checksum")
    return match.group(1).lower()


def source_inventory(directory, names):
    result = {}
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise RuntimeError("Generator did not produce an ordinary nonempty source file: " + name)
        result[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    return result


def upstream_commands(profile):
    if profile.get("installed_upstream_tests") != list(UPSTREAM_TESTS):
        raise RuntimeError("The exact four pinned upstream test commands must be present")
    return UPSTREAM_TESTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", choices=("csmith", "yarpgen-scalar", "yarpgen-loop"), required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--case", choices=("seeded-programs", "runtime-api", "upstream-tests"), required=True)
    args = parser.parse_args()
    parent = args.build if args.build else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=args.resource + "-" + args.case + "-", dir=parent))
    report = {"schema_version": 1, "resource": args.resource, "case": args.case, "status": "running",
              "work": str(work), "commands": [], "programs": [], "oracle": "Same-compiler optimization-level agreement, not an independent reference compiler or proof of all generated programs."}
    environment = dict(os.environ)
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "CPATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH", "LIBRARY_PATH"):
        environment.pop(key, None)

    def run(label, argv, *, cwd=work, negative=False, timeout=120):
        command = [str(x) for x in argv]
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=environment, timeout=timeout)
        (work / (label + ".stdout")).write_text(done.stdout)
        (work / (label + ".stderr")).write_text(done.stderr)
        row = {"label": label, "argv": command, "cwd": str(cwd), "returncode": done.returncode,
               "stdout": label + ".stdout", "stderr": label + ".stderr", "expected_nonzero": negative}
        report["commands"].append(row)
        if (done.returncode == 0) == negative:
            raise RuntimeError("Unexpected exit status for " + label + ": " + str(done.returncode))
        return done.stdout

    try:
        executable = args.prefix / "bin" / ("csmith" if args.resource == "csmith" else "yarpgen")
        if args.case == "seeded-programs":
            run("version", [executable, "--version"])
            run("invalid-option", [executable, "--cpg-invalid-option"], negative=True)
            standards = ("c", "c++") if args.resource != "yarpgen-scalar" else ("c99", "c++14")
            seeds = (1, 7, 42) if args.resource == "csmith" else (1, 7)
            fingerprints = set()
            for standard in standards:
                cpp = "+" in standard
                suffix = "cpp" if cpp else "c"
                compiler = "/usr/bin/g++" if cpp else "/usr/bin/gcc"
                for seed in seeds:
                    label = ("cpp" if cpp else "c") + "-" + str(seed)
                    first, second = work / (label + "-first"), work / (label + "-repeat")
                    first.mkdir()
                    second.mkdir()
                    if args.resource == "csmith":
                        options = ["--seed", str(seed), "--max-funcs", "3", "--max-block-depth", "2", "--max-block-size", "3", "--max-expr-complexity", "5"]
                        if cpp:
                            options += ["--lang-cpp", "--cpp11"]
                        names = ["program." + suffix]
                        for repetition, directory in (("first", first), ("repeat", second)):
                            text = run(label + "-generate-" + repetition, [executable, *options], cwd=directory)
                            (directory / names[0]).write_text(text)
                    else:
                        names = ["driver." + suffix, "func." + suffix, "init.h"]
                        options = ["--seed=" + str(seed), "--std=" + standard]
                        for repetition, directory in (("first", first), ("repeat", second)):
                            run(label + "-generate-" + repetition, [executable, *options], cwd=directory)
                    files = source_inventory(first, names)
                    if source_inventory(second, names) != files:
                        raise RuntimeError("The same fixed seed produced different source bytes: " + label)
                    fingerprints.add(tuple((k, v["sha256"]) for k, v in sorted(files.items())))
                    results = []
                    for optimize in ("-O0", "-O2"):
                        binary = first / ("program" + optimize)
                        sources = [first / name for name in names if name.endswith("." + suffix)]
                        compiler_standard = ("c++17" if args.resource == "csmith" else "c++14") if cpp else "c99"
                        command = [compiler, "-std=" + compiler_standard, optimize, *sources]
                        if args.resource == "csmith":
                            command += ["-I" + str(args.prefix / "include")]
                            if cpp:
                                # The pinned generator can emit narrowing list
                                # initializers (including selected seed 7).
                                # Qualify this explicit GCC compatibility mode;
                                # never advertise it as strict ISO C++ output.
                                command.append("-Wno-narrowing")
                        run(label + "-compile" + optimize, [*command, "-o", binary], timeout=180)
                        text = run(label + "-run" + optimize, [binary], timeout=30)
                        results.append(checksum(args.resource, text))
                    if results[0] != results[1]:
                        raise RuntimeError("O0/O2 generated-program checksum mismatch: " + label)
                    report["programs"].append({"seed": seed, "standard": standard, "files": files,
                                                "repeat_bytes_equal": True, "checksums": results,
                                                "compiler": compiler, "compiler_standard": compiler_standard,
                                                "gnu_narrowing_compatibility": args.resource == "csmith" and cpp,
                                                "optimization_levels": ["O0", "O2"]})
            expected = len(standards) * len(seeds)
            if len(report["programs"]) != expected or len(fingerprints) != expected:
                raise RuntimeError("The generator did not produce every distinct selected program")
            run("compiler-invalid-input", ["/usr/bin/gcc", "-x", "c", "-c", "-o", work / "invalid.o", "/dev/null", "--cpg-invalid-flag"], negative=True)
        elif args.case == "runtime-api":
            if args.resource != "csmith":
                raise ValueError("runtime-api applies only to Csmith")
            code = '#define WRAP_VOLATILES 1\n#include "volatile_runtime.h"\n#include <stdio.h>\n#define TEST(T,V) do { volatile T x = (V); if (volatile_##T##_ptr_read(&x) != x || volatile_##T##_ptr_id(&x) != &x) return 3; } while(0)\nint main(void) { TEST(int8_t,-123); TEST(uint8_t,251); TEST(int16_t,-12345); TEST(uint16_t,54321); TEST(int32_t,-1234567); TEST(uint32_t,UINT32_C(0xfedcba98)); TEST(int64_t,-INT64_C(0x123456789123456)); TEST(uint64_t,UINT64_C(0xfedcba9876543210)); puts("csmith runtime passed"); return 0; }\n'
            source = work / "runtime.c"
            source.write_text(code)
            for mode in ("static", "shared"):
                binary = work / ("runtime-" + mode)
                link = [args.prefix / "lib/libcsmith.a"] if mode == "static" else ["-L" + str(args.prefix / "lib"), "-Wl,-rpath," + str(args.prefix / "lib"), "-lcsmith"]
                run(mode + "-compile", ["/usr/bin/gcc", "-std=c99", "-I" + str(args.prefix / "include"), source, *link, "-o", binary])
                if run(mode + "-run", [binary]) != "csmith runtime passed\n":
                    raise RuntimeError("Csmith installed runtime API did not run")
        else:
            if args.resource != "yarpgen-loop":
                raise ValueError("upstream-tests applies only to loop YARPGen")
            profile = json.loads((args.prefix / "share/compiler-playground/yarpgen-loop/profile.json").read_text())
            for name in upstream_commands(profile):
                run(name, [args.prefix / "libexec/yarpgen-loop" / name], timeout=180)
            report["upstream_tests"] = list(UPSTREAM_TESTS)
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        (work / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
