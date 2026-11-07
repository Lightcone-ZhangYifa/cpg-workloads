#!/usr/bin/env python3
"""Build OCaml, Dune and Menhir from the verified offline source closure."""
import argparse
import os
import shutil
import time
from common import configure, verify_inputs, unpack, run, environment, host_info, write_json

parser = argparse.ArgumentParser()
parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
parser.add_argument("--source", help="Prepared source/material root containing materials/sources.lock.json")
parser.add_argument("--build", help="Independent disposable build directory")
parser.add_argument("--evidence", help="Evidence output directory")
parser.add_argument("--keep-build-dependencies", action="store_true",
                    help="Keep disposable OCaml/Dune compilation trees after verified bootstrap install")
args = parser.parse_args()
ROOT, WORK, EVIDENCE = configure(args.source, args.build, args.evidence)
if not 1 <= args.jobs <= 256:
    raise SystemExit("--jobs must be between 1 and 256")
start = time.monotonic()
lock = verify_inputs()
items = {item["name"]: item for item in lock["sources"]}
src = {name: unpack(item, WORK / "sources" / name) for name, item in items.items()}
prefix = WORK / "bootstrap"
records = []

records.append(run(["./configure", "--prefix=" + str(prefix), "--disable-ocamldoc"],
                   src["ocaml"], "build-01-ocaml-configure.log"))
records.append(run(["make", "-j" + str(args.jobs), "world.opt"], src["ocaml"],
                   "build-02-ocaml-world.log"))
records.append(run(["make", "install"], src["ocaml"], "build-03-bootstrap-install.log"))

if not args.keep_build_dependencies:
    records.append(run([prefix / "bin/ocamlopt", "-version"], prefix,
                       "build-03b-ocaml-version.log", environment(prefix)))
    shutil.rmtree(src["ocaml"])

env = environment(prefix)
records.append(run([prefix / "bin/ocaml", "boot/bootstrap.ml", "-j", str(args.jobs)],
                   src["dune"], "build-04-dune-bootstrap.log", env))
records.append(run([src["dune"] / "_boot/dune.exe", "build", "dune.install", "--release",
                    "--profile", "dune-bootstrap", "-j", str(args.jobs)],
                   src["dune"], "build-05-dune-release.log", env))
records.append(run([src["dune"] / "_boot/dune.exe", "install", "--prefix", str(prefix), "dune"],
                   src["dune"], "build-06-dune-install.log", env))
if not args.keep_build_dependencies:
    records.append(run([prefix / "bin/dune", "--version"], prefix,
                       "build-06b-dune-version.log", env))
    shutil.rmtree(src["dune"])
records.append(run([prefix / "bin/dune", "build", "--root", str(src["menhir"]),
                   "--only-packages", "menhir,menhirLib,menhirSdk,menhirCST", "@install",
                   "--profile", "release", "-j", str(args.jobs)],
                   src["menhir"], "build-07-menhir.log", env))
write_json(EVIDENCE / "build.json", {
    "schema_version": 1, "resource_id": "menhir", "success": True,
    "source_build": {"ocaml": "4.14.2", "dune": "3.17.2", "menhir": "20250912"},
    "bootstrap_prefix": str(prefix), "host": host_info(), "commands": records,
    "seconds": round(time.monotonic() - start, 3), "opam_invoked": False,
    "dependency_build_trees_kept": args.keep_build_dependencies,
    "scope": "Native OCaml compiler, Dune release, Menhir generator and 3 libraries; Coq backend and entire upstream test suite not built."})
print("SOURCE_BUILD_PASS", flush=True)
