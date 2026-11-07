#!/usr/bin/env python3
"""Install only from a completed local build; never fetch or modify the host OS."""
import argparse
import json
import os
import shutil
from pathlib import Path
from common import configure, verify_inputs, run, environment, host_info, write_json, sha256

p = argparse.ArgumentParser()
p.add_argument("--source")
p.add_argument("--build")
p.add_argument("--prefix", required=True)
p.add_argument("--evidence")
args = p.parse_args()
ROOT, WORK, EVIDENCE = configure(args.source, args.build, args.evidence)
lock = verify_inputs()
prefix = Path(args.prefix).resolve()
if prefix.exists() and any(prefix.iterdir()):
    raise SystemExit("Refusing to merge into a nonempty prefix; choose an empty independent prefix")
bootstrap = WORK / "bootstrap"
menhir_source = WORK / "sources/menhir"
if not (bootstrap / "bin/dune").is_file() or not (menhir_source / "_build/default/menhir.install").is_file():
    raise SystemExit("Complete recipe/build.py in the same --build directory first")
shutil.copytree(bootstrap, prefix, symlinks=True, dirs_exist_ok=True)
env = environment(bootstrap)
result = run([bootstrap / "bin/dune", "install", "--root", str(menhir_source),
              "--prefix", str(prefix), "menhir", "menhirLib", "menhirSdk", "menhirCST"],
             menhir_source, "install-menhir.log", env)
abi_records = []
for name in ("menhir", "dune", "ocamlrun", "ocamlc.opt", "ocamlopt.opt"):
    abi_records.append(run(["ldd", prefix / "bin" / name], prefix,
                           "abi-" + name + ".log", env))

# Preserve the compiler files and use explicit runtime invocation for bytecode
# tools. OCaml 4.14 embeds its configure-time prefix in shebangs and defaults.
# The wrappers make the documented core compiler toolchain resolve this prefix.
original = prefix / "libexec/ocaml-original"
original.mkdir(parents=True, exist_ok=True)
wrapped = []
for tool in sorted((prefix / "bin").iterdir()):
    if not tool.name.startswith("ocaml") or tool.name == "ocamlyacc":
        continue
    data = tool.read_bytes()[:4]
    target = original / tool.name
    shutil.move(str(tool), str(target))
    mode = "native" if data == b"\x7fELF" else "bytecode"
    invoke = ('exec "$cpg_prefix/libexec/ocaml-original/' + tool.name + '" "$@"') if mode == "native" else (
        'exec "$cpg_prefix/bin/ocamlrun" "$cpg_prefix/libexec/ocaml-original/' + tool.name + '" "$@"')
    tool.write_text('#!/bin/sh\nset -eu\ncpg_prefix=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
                    'export OCAMLLIB="$cpg_prefix/lib/ocaml"\n'
                    'export CAML_LD_LIBRARY_PATH="$cpg_prefix/lib/ocaml/stublibs"\n' + invoke + '\n')
    tool.chmod(0o755)
    wrapped.append({"tool": tool.name, "mode": mode})

license_dir = prefix / "share/cpg-menhir/licenses"
license_dir.mkdir(parents=True, exist_ok=True)
for source in (ROOT / "licenses").iterdir():
    if source.is_file():
        shutil.copy2(source, license_dir / source.name)
for name, paths in {
    "ocaml": ["LICENSE", "COPYING", "LICENSE.QPL"],
    "dune": ["LICENSE.md"],
    "menhir": ["LICENSE", "fix/LICENSE", "pprint/LICENSE", "coq-menhirlib/LICENSE"],
}.items():
    for rel in paths:
        source = WORK / "sources" / name / rel
        if source.is_file():
            dest_name = name + "-" + rel.replace("/", "-")
            shutil.copy2(source, license_dir / dest_name)
shutil.copy2(ROOT / "materials/sources.lock.json", prefix / "share/cpg-menhir/sources.lock.json")
write_json(EVIDENCE / "install.json", {"success": True, "prefix": str(prefix),
           "command": result, "dynamic_dependencies": abi_records,
           "wrapped_ocaml_tools": wrapped, "host": host_info(),
           "scope": "Menhir plus exact source-built OCaml and Dune closure; wrapper relocation is checked separately.",
           "files": {"bin/menhir": sha256(prefix / "bin/menhir"), "bin/dune": sha256(prefix / "bin/dune")}})
print("INSTALL_PASS", prefix)
