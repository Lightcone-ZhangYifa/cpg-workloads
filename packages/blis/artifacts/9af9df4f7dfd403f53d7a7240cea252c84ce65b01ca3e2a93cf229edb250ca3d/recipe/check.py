#!/usr/bin/env python3
"""Check actual BLIS API consumers and the upstream numerical fast matrix."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--case", choices=("api", "upstream"), required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    environment = dict(os.environ, LC_ALL="C", BLIS_NUM_THREADS="1", BLIS_THREAD_IMPL="pthreads", OMP_NUM_THREADS="1")
    for key in tuple(environment):
        if key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "LIBRARY_PATH", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH") or key.endswith("_NT"):
            environment.pop(key, None)
    result = {"status": "running", "case": args.case, "commands": [], "prefix": str(prefix)}

    def run(argv, *, env=environment, cwd=None):
        command = [str(x) for x in argv]
        completed = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=300)
        result["commands"].append({"argv": command, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode:
            raise RuntimeError("An installed BLIS check failed")
        return completed

    try:
        profile = json.loads((prefix / "share/compiler-playground/blis/profile.json").read_text())
        if profile.get("version") != "2.1" or profile.get("configuration") != "generic" or profile.get("upstream_blis_pass_rows",0)<100:
            raise RuntimeError("Missing or incomplete BLIS profile")
        with tempfile.TemporaryDirectory(prefix="cpg-blis-check-") as directory:
            temporary = Path(directory)
            if args.case == "upstream":
                source = prefix / "share/blis/source/testsuite"
                env = dict(environment, LD_LIBRARY_PATH=str(prefix / "lib"))
                completed = run([prefix / "libexec/blis/test_libblis.x", "-g", source / "input.general.fast", "-o", source / "input.operations.fast"], env=env,cwd=temporary)
                output = temporary / "output.testsuite"
                output.write_text(completed.stdout)
                run(["/bin/sh", source / "check-blistest.sh", output])
                passes = len(re.findall(r"\bPASS\b", completed.stdout))
                if passes != profile["upstream_blis_pass_rows"] or "FAILURE" in completed.stdout or "Exiting normally" not in completed.stdout:
                    raise RuntimeError("Upstream numerical results are incomplete or changed")
                result.update(upstream_pass_rows=passes, upstream_configuration="original fast matrix", thread_count=1)
            else:
                result["consumers"] = []
                for kind in ("shared", "static"):
                    executable = temporary / kind
                    library = prefix / "lib" / ("libblis.so" if kind == "shared" else "libblis.a")
                    run(["/usr/bin/gcc", "-std=c99", "-O2", "-I" + str(prefix / "include/blis"), Path(__file__).with_name("api.c"),
                         library, "-pthread", "-lm", "-Wl,-rpath," + str(prefix / "lib"), "-o", executable])
                    row = json.loads(run([executable]).stdout)
                    if row.get("dgemm_cases") != 216 or row.get("thread_settings") != [1,2] or not row.get("strided_blas1") or not row.get("native_typed_api"):
                        raise RuntimeError("The installed BLAS consumer did not complete every declared case")
                    rejected = subprocess.run([str(executable),"--invalid"], capture_output=True,text=True,env=environment,timeout=30)
                    result["commands"].append({"argv":[str(executable),"--invalid"],"returncode":rejected.returncode,"stdout":rejected.stdout,"stderr":rejected.stderr})
                    if rejected.returncode in (0,42) or not (rejected.stdout+rejected.stderr).strip():
                        raise RuntimeError("An invalid CBLAS order was not explicitly rejected")
                    result["consumers"].append({"link":kind,**row,"invalid_order":"rejected"})
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed",error=f"{type(error).__name__}: {error}")
        raise
    finally:
        print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
