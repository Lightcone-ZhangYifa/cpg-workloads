#!/usr/bin/env python3
"""Check installed afl-fuzz by running a bounded non-instrumented target.

This checks input mutation, target execution and execution accounting. It does
not qualify LLVM instrumentation, QEMU/FRIDA/Unicorn modes or benchmark results.
The flags are present in AFL++'s pinned dbaf11913c1b2702dee5b4d3dcfffd52f1defe50
src/afl-fuzz.c. No compiler or network access is needed by this check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


TARGET = """from pathlib import Path
import hashlib
import sys

data = Path(sys.argv[1]).read_bytes()
with Path(sys.argv[2]).open('a', encoding='ascii') as record:
    record.write(hashlib.sha256(data).hexdigest() + '\\n')
"""


def check(prefix: Path):
    executable = prefix / "bin/afl-fuzz"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("The installed afl-fuzz executable is missing")
    with tempfile.TemporaryDirectory(prefix="cpg-afl-blackbox-") as directory:
        root = Path(directory)
        seeds, output = root / "seeds", root / "output"
        seeds.mkdir()
        seed = b"CPG AFL functional seed: 0123456789abcdef\n"
        (seeds / "seed").write_bytes(seed)
        target, observations = root / "target.py", root / "observed-inputs.txt"
        target.write_text(TARGET, encoding="utf-8")
        # An inherited mutator or synchronization setting would change the scope
        # of this small check. No system-wide settings are changed.
        environment = {name: value for name, value in os.environ.items() if not name.startswith("AFL_")}
        environment.update(AFL_NO_UI="1", AFL_NO_AFFINITY="1", AFL_SKIP_CPUFREQ="1",
                           AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES="1", LC_ALL="C",
                           PYTHONDONTWRITEBYTECODE="1")
        argv = [str(executable), "-n", "-V", "2", "-E", "32", "-s", "12345",
                "-m", "none", "-t", "1000", "-i", str(seeds), "-o", str(output),
                "--", sys.executable, "-B", str(target), "@@", str(observations)]
        process = subprocess.Popen(argv, cwd=root, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            log, _ = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise RuntimeError("Bounded afl-fuzz run exceeded 20 seconds") from None
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        if process.returncode != 0:
            raise RuntimeError("afl-fuzz returned " + str(process.returncode) + ": " + log[-2500:])
        candidates = [output / "fuzzer_stats", output / "default/fuzzer_stats"]
        stats_path = next((path for path in candidates if path.is_file()), None)
        if stats_path is None:
            raise RuntimeError("afl-fuzz did not produce execution statistics")
        stats = {}
        for line in stats_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition(":")
            if separator:
                stats[key.strip()] = value.strip()
        try:
            executions = int(stats["execs_done"])
        except (KeyError, ValueError):
            raise RuntimeError("afl-fuzz execution count is missing or malformed") from None
        if not observations.is_file():
            raise RuntimeError("The target was never invoked with an input")
        observed = observations.read_text(encoding="ascii").splitlines()
        unique = set(observed)
        if executions < 2 or len(observed) < 2:
            raise RuntimeError("afl-fuzz did not execute the target repeatedly")
        if hashlib.sha256(seed).hexdigest() not in unique:
            raise RuntimeError("The supplied seed did not reach the target")
        if len(unique) < 2:
            raise RuntimeError("No mutated input reached the target")
        return {"status": "passed", "scope": "afl-fuzz non-instrumented mutation and execution",
                "execs_done": executions, "target_invocations": len(observed),
                "distinct_target_inputs": len(unique), "llvm_instrumentation": "not_tested",
                "qemu_frida_unicorn_modes": "not_tested"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.prefix.resolve())
    except (OSError, RuntimeError, UnicodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
