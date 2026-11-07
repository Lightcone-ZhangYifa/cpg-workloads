#!/usr/bin/env python3
"""Check the one assembled AArch64 musl toolchain without target execution."""
import argparse
from pathlib import Path
import json
from check_link_tools import Run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prefix", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    run = Run(args.output)
    projection = json.loads((prefix / "share/cpg-buildroot/development-projection.json").read_text())
    run.check(projection["original_archive_preserved"] and len([row for row in projection["removed_runtime_only_links"] if row["path"].startswith("sdk/")]) == 6,
              "six exact runtime-only SDK links recorded in development projection; original archive retained")
    tools = prefix / "host/bin"
    stem = "aarch64-buildroot-linux-musl-"
    cc, cxx, ar = (tools / (stem + name) for name in ("gcc", "g++", "ar"))
    sysroot = Path(run.cmd([cc, "-print-sysroot"]).strip())
    run.check(sysroot.is_dir() and sysroot.resolve().is_relative_to(prefix),
              "compiler uses assembled sysroot inside its independent prefix")
    run.check("aarch64" in run.cmd([cc, "-dumpmachine"]), "fixed AArch64 compiler tuple")
    run.file("calc.c", "long cpg_calc(int n){long x=7;for(int i=0;i<n;i++)x+=i*i+3;return x;}\n")
    run.file("main.c", '#include <stdio.h>\nextern long cpg_calc(int);\n_Thread_local int tls=11;\nint main(void){printf("%ld,%d\\n",cpg_calc(10),tls);return 0;}\n')
    run.cmd([cc, "-O2", "-c", "calc.c", "-o", "calc.o"])
    run.cmd([ar, "rcs", "libcalc.a", "calc.o"])
    run.cmd([cc, "-O2", "main.c", "libcalc.a", "-o", "hello-aarch64"])
    headers = run.cmd(["readelf", "-hW", "-lW", "-sW", "hello-aarch64"])
    run.check("AArch64" in headers and "ELF64" in headers, "AArch64 ELF64 executable")
    run.check("/lib/ld-musl-aarch64.so.1" in headers, "musl interpreter matches selected toolchain")
    run.check("cpg_calc" in headers and "TLS" in headers, "archive symbol and thread local data linked")
    run.file("cpp.cpp", '#include <vector>\n#include <stdexcept>\nint main(){try{std::vector<int> x{19,23};if(x[0]+x[1]==42)throw std::runtime_error("ok");}catch(const std::exception&){return 0;}return 1;}\n')
    run.cmd([cxx, "-O2", "-static", "cpp.cpp", "-o", "cpp-aarch64-static"])
    cpp = run.cmd(["readelf", "-hW", "-lW", "-SW", "cpp-aarch64-static"])
    run.check("AArch64" in cpp and "INTERP" not in cpp, "C++ static cross-link resolves sysroot libraries")
    run.check(".eh_frame" in cpp, "C++ exception/unwind sections present")
    run.file("missing.c", "extern int cpg_missing(void);int main(void){return cpg_missing();}\n")
    error = run.cmd([cc, "missing.c", "-o", "missing"], expect="nonzero")
    run.check("cpg_missing" in error, "undefined cross-link symbol rejected")
    result = run.save(target="aarch64-buildroot-linux-musl", host="x86_64-linux",
                      compiler_source_rebuild=False, buildroot_external_toolchain_assembly=True,
                      target_execution=None, full_rootfs_or_board_matrix=False)
    print(json.dumps({"status": result["status"], "assertions": result["assertion_count"],
                      "target_execution": None, "scope": "one AArch64 musl external-toolchain profile"}))


if __name__ == "__main__":
    main()
