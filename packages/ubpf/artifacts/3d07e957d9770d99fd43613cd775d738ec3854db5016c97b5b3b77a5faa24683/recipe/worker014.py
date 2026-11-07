#!/usr/bin/env python3
"""CPG worker014 offline build/install/check. No network or package installation.

Use an existing toolchain, or --tool-prefix containing already extracted dependencies.
The prebuilt check needs Linux x86_64, glibc 2.38+, libelf, and zlib. New probes
link the baseline libbpf 1.3.0 static library. No operation loads BPF into a kernel.
"""
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
import time

ROOT = Path(__file__).resolve().parent
RESOURCES = ("ubpf", "wasm-spec", "bpftool", "libbpf")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def verify_inputs():
    locks = json.loads((ROOT / "metadata/source-locks.json").read_text())
    for row in locks:
        p = ROOT / "raw" / row["filename"]
        if not p.is_file() or p.stat().st_size != row["bytes"] or sha(p) != row["sha256"]:
            raise RuntimeError("source identity mismatch: " + row["filename"])
    return {r["name"]: r for r in locks}


def environment(tool_prefix):
    env = os.environ.copy()
    # These are build-time switches, not evidence of OS-level network isolation.
    env.update({"CARGO_NET_OFFLINE": "true", "PIP_NO_INDEX": "1", "GIT_TERMINAL_PROMPT": "0"})
    if tool_prefix:
        base = tool_prefix.resolve()
        env["PATH"] = str(base / "usr/bin") + os.pathsep + env.get("PATH", "")
        lib = str(base / "usr/lib/x86_64-linux-gnu")
        for key in ("LD_LIBRARY_PATH", "LIBRARY_PATH"):
            env[key] = lib + (os.pathsep + env[key] if env.get(key) else "")
        env["C_INCLUDE_PATH"] = str(base / "usr/include") + (os.pathsep + env["C_INCLUDE_PATH"] if env.get("C_INCLUDE_PATH") else "")
        env["PKG_CONFIG_PATH"] = lib + "/pkgconfig"
        env["OCAMLLIB"] = str(base / "usr/lib/ocaml")
        env["OCAMLPATH"] = str(base / "usr/lib/ocaml")
        env["CAML_LD_LIBRARY_PATH"] = str(base / "usr/lib/ocaml/stublibs")
    return env


class Runner:
    def __init__(self, out, env):
        self.out = out.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.env = env
        self.rows = []

    def run(self, label, argv, cwd=None, reject=False, timeout=300):
        start = time.monotonic()
        p = subprocess.run([str(x) for x in argv], cwd=cwd, env=self.env,
                           capture_output=True, timeout=timeout)
        a, b = self.out / (label + ".stdout"), self.out / (label + ".stderr")
        a.write_bytes(p.stdout)
        b.write_bytes(p.stderr)
        ok = p.returncode != 0 if reject else p.returncode == 0
        self.rows.append({"label": label, "argv": [str(x) for x in argv],
                          "cwd": str(cwd) if cwd else None, "returncode": p.returncode,
                          "expectation": "nonzero_rejection" if reject else "success",
                          "elapsed_seconds": round(time.monotonic() - start, 6),
                          "stdout_sha256": sha(a), "stderr_sha256": sha(b), "passed": ok})
        self.save()
        if not ok:
            raise RuntimeError(f"{label}: unexpected return code {p.returncode}; see {b}")
        return p.stdout

    def save(self):
        (self.out / "commands.json").write_text(json.dumps(self.rows, indent=2) + "\n")


def unpack(name, locks, work):
    row = locks[name]
    dest = work / ("source-" + name)
    dest.mkdir()
    with tarfile.open(ROOT / "raw" / row["filename"]) as t:
        t.extractall(dest, filter="data")
    roots = list(dest.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise RuntimeError("unexpected source archive root")
    return roots[0]


def build(args):
    locks = verify_inputs()
    work = args.work_dir.resolve()
    if work.exists() and any(work.iterdir()):
        raise RuntimeError("build work directory must be empty")
    work.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix.resolve()
    for sub in ("bin", "include", "lib", "tests/bpf", "tests/spec", "metadata"):
        (prefix / sub).mkdir(parents=True, exist_ok=True)
    env = environment(args.tool_prefix)
    run = Runner(args.report, env)
    selected = RESOURCES if args.resource == "all" else (args.resource,)
    if "ubpf" in selected:
        src = unpack("ubpf", locks, work)
        builddir = work / "ubpf-build"
        run.run("ubpf-configure", ["cmake", "-S", src, "-B", builddir,
                "-DCMAKE_BUILD_TYPE=Release", "-DUBPF_ENABLE_TESTS=OFF",
                "-DUBPF_SKIP_EXTERNAL=ON", "-DUBPF_ENABLE_INSTALL=ON",
                "-DUBPF_INSTALL_GIT_HOOKS=OFF", f"-DCMAKE_INSTALL_PREFIX={prefix}"])
        run.run("ubpf-build", ["cmake", "--build", builddir, "-j2"])
        run.run("ubpf-install", ["cmake", "--install", builddir])
        shutil.copy2(src / "vm/ebpf.h", prefix / "include/ebpf.h")
        run.run("ubpf-probe-build", ["cc", "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I" + str(prefix / "include"), ROOT / "tests/ubpf_probe.c",
                prefix / "lib/libubpf.a", "-lm", "-o", prefix / "bin/ubpf-probe"])
    if "wasm-spec" in selected:
        src = unpack("wasm-spec", locks, work)
        run.run("wasm-spec-build", ["dune", "build", "-j2", "wasm.exe"], cwd=src / "interpreter")
        shutil.copy2(src / "interpreter/_build/default/wasm.exe", prefix / "bin/wasm-reference")
        for f in (ROOT / "payload/tests/spec").iterdir():
            shutil.copy2(f, prefix / "tests/spec" / f.name)
        shutil.copy2(ROOT / "metadata/wasm-spec-tests.jsonl", prefix / "metadata/wasm-spec-tests.jsonl")
    if "bpftool" in selected:
        src = unpack("bpftool", locks, work)
        libsrc = unpack("bpftool-libbpf", locks, work)
        shutil.copytree(libsrc, src / "libbpf", dirs_exist_ok=True)
        builddir = work / "bpftool-build"
        builddir.mkdir()
        run.run("bpftool-build", ["make", "-C", src / "src", "-j2", f"OUTPUT={builddir}/",
                "VMLINUX_BTF=", "VMLINUX_H=", "feature-clang-bpf-co-re=0"])
        shutil.copy2(builddir / "bpftool", prefix / "bin/bpftool")
    if "libbpf" in selected:
        bpf = prefix / "tests/bpf"
        static_query = run.run("libbpf-static-library", ["cc", "-print-file-name=libbpf.a"]).decode().strip()
        static_libbpf = Path(static_query)
        if not static_libbpf.is_file():
            raise RuntimeError("the existing libbpf 1.3 static development library is required")
        clang = args.clang or shutil.which("clang-18", path=env["PATH"]) or shutil.which("clang", path=env["PATH"])
        if not clang:
            raise RuntimeError("a local clang with the BPF target is required")
        for n in ("a", "b"):
            run.run("bpf-input-" + n, [clang, "--target=bpf", "-O2", "-g", "-c",
                    ROOT / f"tests/input_{n}.bpf.c", "-o", bpf / f"input_{n}.bpf.o"])
        run.run("libbpf-probe-build", ["cc", "-O2", "-Wall", "-Wextra", "-Werror",
                ROOT / "tests/libbpf_probe.c", static_libbpf, "-lelf", "-lz", "-o", prefix / "bin/libbpf-probe"])
        run.run("libbpf-link", [prefix / "bin/libbpf-probe", bpf / "input_a.bpf.o", bpf / "input_b.bpf.o", bpf / "linked.bpf.o"])
        header = run.run("skeleton-generate", [prefix / "bin/bpftool", "gen", "skeleton", bpf / "linked.bpf.o", "name", "cpg_probe"])
        (bpf / "cpg_probe.skel.h").write_bytes(header)
        run.run("skeleton-probe-build", ["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-I" + str(bpf),
                ROOT / "tests/skeleton_probe.c", static_libbpf, "-lelf", "-lz", "-o", prefix / "bin/skeleton-probe"])
    print(json.dumps({"build": "passed", "resources": selected, "prefix": str(prefix), "report": str(run.out)}))


def check(args):
    prefix = args.prefix.resolve()
    run = Runner(args.report, environment(args.tool_prefix))
    selected = RESOURCES if args.resource == "all" else (args.resource,)
    summary = {"schema_version": 1, "platform": platform.platform(), "resources": {},
               "scope": "controlled local native CPU tests; no kernel load/attach/probe; no benchmark claim"}
    if "ubpf" in selected:
        data = run.run("ubpf-controlled", [prefix / "bin/ubpf-probe"])
        cases = [json.loads(x) for x in data.decode().splitlines()]
        if len(cases) != 37 or not all(x["pass"] for x in cases):
            raise RuntimeError("uBPF result oracle mismatch")
        summary["resources"]["ubpf"] = {"passed": True, "runtime_comparisons": 36, "invalid_program_rejected": 1,
                                         "profile": "legacy; only controlled test bytecode executed"}
    if "wasm-spec" in selected:
        for n in ("i32.wast", "memory.wast", "func.wast", "unreachable.wast"):
            run.run("wasm-" + n, [prefix / "bin/wasm-reference", prefix / "tests/spec" / n])
        negatives = {
            "wrong-result": '(module (func (export "f") (result i32) i32.const 42))\n(assert_return (invoke "f") (i32.const 43))\n',
            "invalid-module": '(module (func (result i32) i64.const 0))\n',
            "unreachable": '(module (func (export "f") unreachable))\n(invoke "f")\n',
        }
        expected_messages = {"wrong-result": "wrong return values", "invalid-module": "type mismatch", "unreachable": "unreachable"}
        for name, data in negatives.items():
            p = run.out / (name + ".wast")
            p.write_text(data)
            run.run("wasm-negative-" + name, [prefix / "bin/wasm-reference", p], reject=True)
            msg = (run.out / ("wasm-negative-" + name + ".stderr")).read_text()
            if expected_messages[name] not in msg:
                raise RuntimeError("reference interpreter rejected for an unexpected reason: " + name)
        summary["resources"]["wasm-spec"] = {"passed": True, "official_files_executed": 4, "negative_oracles": 3,
                                              "complete_suite_executed": False}
    bpf = prefix / "tests/bpf"
    if "libbpf" in selected:
        linked = run.out / "linked.bpf.o"
        result = json.loads(run.run("libbpf-offline", [prefix / "bin/libbpf-probe", bpf / "input_a.bpf.o", bpf / "input_b.bpf.o", linked]))
        if result["libbpf"] != "v1.3" or result["kernel_load"] or result["programs"] != 1:
            raise RuntimeError("wrong libbpf runtime or fixture metadata")
        cases = [json.loads(x) for x in run.run("linked-execution", [prefix / "bin/ubpf-probe", "--elf", linked]).splitlines()]
        if len(cases) != 5 or not all(x["pass"] for x in cases):
            raise RuntimeError("linked ELF execution oracle failed")
        summary["resources"]["libbpf"] = {"passed": True, "baseline_id": "apt.libbpf-dev", "runtime": result,
                                           "linked_elf_runtime_comparisons": 5, "core_relocation_qualified": False}
    if "bpftool" in selected:
        version = run.run("bpftool-version", [prefix / "bin/bpftool", "version"]).decode()
        if "bpftool v7.3.0" not in version:
            raise RuntimeError("wrong bpftool version")
        btf = run.run("bpftool-btf", [prefix / "bin/bpftool", "btf", "dump", "file", bpf / "linked.bpf.o", "format", "raw"])
        if b"STRUCT 'cpg_context' size=8" not in btf or b"FUNC 'cpg_add'" not in btf:
            raise RuntimeError("BTF semantic fields missing")
        header = run.run("bpftool-skeleton", [prefix / "bin/bpftool", "gen", "skeleton", bpf / "linked.bpf.o", "name", "cpg_probe"])
        if header != (bpf / "cpg_probe.skel.h").read_bytes():
            raise RuntimeError("generated skeleton differs from checked fixture")
        opened = json.loads(run.run("bpftool-skeleton-open", [prefix / "bin/skeleton-probe"]))
        if not opened["skeleton_open"] or opened["kernel_load"] or opened["attach"]:
            raise RuntimeError("skeleton API oracle failed")
        bad = run.out / "malformed.btf"
        bad.write_bytes(b"not an ELF or BTF object\n")
        run.run("bpftool-reject-malformed", [prefix / "bin/bpftool", "btf", "dump", "file", bad, "format", "raw"], reject=True)
        summary["resources"]["bpftool"] = {"passed": True, "offline_btf_skeleton": True,
                                            "kernel_checkpoint": "750011e239a50873251c16207b0fe78eabf8577e",
                                            "current_kernel_qualified": False}
    summary["passed"] = all(x["passed"] for x in summary["resources"].values())
    (run.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def install(args):
    manifest = json.loads((ROOT / "metadata/payload-manifest.json").read_text())
    dest = args.prefix.resolve()
    for row in manifest:
        src = ROOT / "payload" / row["path"]
        if sha(src) != row["sha256"] or src.stat().st_size != row["bytes"]:
            raise RuntimeError("payload identity mismatch: " + row["path"])
        dst = dest / row["path"]
        if dst.exists() and (not dst.is_file() or sha(dst) != row["sha256"]):
            raise RuntimeError("refusing to replace a different existing file: " + str(dst))
    for row in manifest:
        src, dst = ROOT / "payload" / row["path"], dest / row["path"]
        if src.resolve() == dst.resolve():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(json.dumps({"installed": len(manifest), "prefix": str(dest), "network": False}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("verify-inputs", "install", "check", "build"))
    p.add_argument("--resource", choices=("all",) + RESOURCES, default="all")
    p.add_argument("--prefix", type=Path, default=ROOT / "payload")
    p.add_argument("--report", type=Path, default=Path("worker014-check"))
    p.add_argument("--work-dir", type=Path, default=Path("worker014-build"))
    p.add_argument("--tool-prefix", type=Path)
    p.add_argument("--clang")
    args = p.parse_args()
    if args.action == "verify-inputs":
        print(json.dumps({"verified": list(verify_inputs())}))
    else:
        globals()[args.action](args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        print("worker014: " + str(exc), file=sys.stderr)
        sys.exit(1)
