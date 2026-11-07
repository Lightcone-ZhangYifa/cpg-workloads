#!/usr/bin/env python3
"""Meaningful offline compiler and parser checks with explicit expected failures."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from common import configure, verify_inputs, run, environment, write_json, sha256

p = argparse.ArgumentParser()
p.add_argument("--source")
p.add_argument("--build", help="Independent directory for generated check artifacts")
p.add_argument("--prefix", required=True)
p.add_argument("--evidence")
args = p.parse_args()
ROOT, WORK, EVIDENCE = configure(args.source, args.build, args.evidence)
verify_inputs()
prefix = Path(args.prefix).resolve()
env = environment(prefix)
records = []
cases = []
versions = {}
for name, flag in (("ocamlc", "-version"), ("ocamlopt", "-version"), ("dune", "--version"), ("menhir", "--version")):
    r = subprocess.run([str(prefix / "bin" / name), flag], env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Version command failed: " + name + " " + r.stderr)
    versions[name] = r.stdout.strip()
if versions != {"ocamlc": "4.14.2", "ocamlopt": "4.14.2", "dune": "3.17.2", "menhir": "menhir, version 20250912"}:
    raise RuntimeError("Unexpected pinned versions: " + repr(versions))

# These exercise the interpreted compiler tools as well as the native ones;
# prefix relocation must not accidentally depend on the original ocamlrun.
r = subprocess.run([str(prefix / "bin/ocaml"), "-noinit", "-noprompt", "-no-version"],
                   input='print_endline "OCAML_TOPLEVEL_OK";;\n', env=env,
                   capture_output=True, text=True)
cases.append({"id":"closure:ocaml-toplevel","returncode":r.returncode,
              "stdout":r.stdout,"stderr":r.stderr,
              "pass":r.returncode==0 and "OCAML_TOPLEVEL_OK" in r.stdout})
byte_dir = WORK / "check-bytecode"
byte_dir.mkdir(parents=True, exist_ok=True)
(byte_dir / "smoke.ml").write_text('let () = print_endline "OCAML_BYTECODE_OK"\n')
records.append(run([prefix / "bin/ocamlc", "-use-runtime", prefix / "bin/ocamlrun",
                    "smoke.ml", "-o", "smoke.byte"], byte_dir,
                   "check-bytecode-compile.log", env))
r = subprocess.run([str(prefix / "bin/ocamlrun"), str(byte_dir / "smoke.byte")],
                   env=env, capture_output=True, text=True)
cases.append({"id":"closure:bytecode-runtime","returncode":r.returncode,
              "stdout":r.stdout,"stderr":r.stderr,
              "pass":r.returncode==0 and r.stdout.strip()=="OCAML_BYTECODE_OK"})
(byte_dir / "runtimeprobe.ml").write_text(
    'let () = Printf.printf "UNIX_PID_POSITIVE=%b\\n" (Unix.getpid () > 0)\n')
records.append(run([prefix / "bin/ocamlc", "-use-runtime", prefix / "bin/ocamlrun",
                    "unix.cma", "runtimeprobe.ml", "-o", "runtimeprobe.byte"], byte_dir,
                   "check-bytecode-unix-compile.log", env))
r = subprocess.run([str(prefix / "bin/ocamlrun"), str(byte_dir / "runtimeprobe.byte")],
                   env=env, capture_output=True, text=True)
cases.append({"id":"closure:bytecode-unix-shared-stub","returncode":r.returncode,
              "stdout":r.stdout,"stderr":r.stderr,
              "pass":r.returncode==0 and r.stdout.strip()=="UNIX_PID_POSITIVE=true"})

for mode in ("code", "table"):
    dest = WORK / ("check-" + mode)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("calc.mly", "lexer.mll", "main.ml", "recover.ml"):
        shutil.copy2(ROOT / "examples" / name, dest / name)
    command = [prefix / "bin/menhir", "--strict", "--infer", "--explain", "--dump"]
    if mode == "table":
        command += ["--table", "--inspection"]
    records.append(run(command + ["calc.mly"], dest, "check-" + mode + "-generate.log", env))
    records.append(run([prefix / "bin/ocamllex", "lexer.mll"], dest, "check-" + mode + "-lexer.log", env))
    lib = prefix / "lib/menhirLib"
    includes = ["-I", str(lib)] if mode == "table" else []
    records.append(run([prefix / "bin/ocamlopt"] + includes + ["-c", "calc.mli", "calc.ml", "lexer.ml"],
                       dest, "check-" + mode + "-compile.log", env))
    runtime = [str(lib / "menhirLib.cmxa")] if mode == "table" else []
    records.append(run([prefix / "bin/ocamlopt"] + includes + runtime + ["calc.cmx", "lexer.cmx", "main.ml", "-o", "calculator"],
                       dest, "check-" + mode + "-link.log", env))
    if mode == "table":
        records.append(run([prefix / "bin/ocamlopt"] + includes + runtime + ["calc.cmx", "lexer.cmx", "recover.ml", "-o", "calculator-recover"],
                           dest, "check-table-recovery-link.log", env))
    for expr, expected in (("2+3*4",14), ("(2+3)*4",20), ("-7+2*5",3), ("9-3-2",4), ("20/5/2",2), ("42",42)):
        r = subprocess.run([str(dest / "calculator"), expr], env=env, capture_output=True, text=True)
        ok = r.returncode == 0 and r.stdout.strip() == str(expected)
        cases.append({"id": mode + ":positive:" + expr,"input":expr,"expected":expected,"returncode":r.returncode,"stdout":r.stdout,"stderr":r.stderr,"pass":ok})
    for expr, expected_status, diagnostic in (("2+*3",2,"SYNTAX_ERROR"), ("(2+3",2,"SYNTAX_ERROR"), ("2&3",2,"LEXICAL_ERROR"), ("2/0",3,"DIVISION_BY_ZERO")):
        r = subprocess.run([str(dest / "calculator"), expr], env=env, capture_output=True, text=True)
        cases.append({"id":mode+":negative:"+expr,"input":expr,"expected_returncode":expected_status,"returncode":r.returncode,"stdout":r.stdout,"stderr":r.stderr,"pass":r.returncode == expected_status and diagnostic in r.stderr})

dest = WORK / "check-conflict"
dest.mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / "examples/ambiguous.mly", dest / "ambiguous.mly")
r = subprocess.run([str(prefix / "bin/menhir"), "--strict", "--explain", "--dump", "ambiguous.mly"],cwd=dest,env=env,capture_output=True,text=True)
(EVIDENCE / "check-conflict.stdout.txt").write_text(r.stdout)
(EVIDENCE / "check-conflict.stderr.txt").write_text(r.stderr)
conflicts = (dest / "ambiguous.conflicts").read_text()
shutil.copy2(dest / "ambiguous.conflicts", EVIDENCE / "ambiguous.conflicts")
shutil.copy2(dest / "ambiguous.automaton", EVIDENCE / "ambiguous.automaton")
cases.append({"id":"conflict:ambiguous-arithmetic","returncode":r.returncode,"expected_returncode":"nonzero","stderr":r.stderr,"explanation_bytes":len(conflicts),"pass":r.returncode != 0 and "shift/reduce" in conflicts and "conflict" in r.stderr.lower()})

recover = WORK / "check-table/calculator-recover"
for expr,value,deleted in (("2+3*4",14,[]), ("2 + * 3",5,["STAR"]), ("2 + * 3 + ) 4",9,["STAR","RPAREN"])):
    r=subprocess.run([str(recover),expr],env=env,capture_output=True,text=True)
    result=json.loads(r.stdout) if r.returncode==0 else {}
    actual=[item["deleted_token"] for item in result.get("recoveries",[])]
    cases.append({"id":"recovery:"+expr,"input":expr,"expected_value":value,"expected_deleted_tokens":deleted,"result":result,"returncode":r.returncode,"stderr":r.stderr,"pass":r.returncode==0 and result.get("value")==value and actual==deleted})
r=subprocess.run([str(recover),"2 +"],env=env,capture_output=True,text=True)
cases.append({"id":"recovery:incomplete-eof-rejected","returncode":r.returncode,"stderr":r.stderr,"pass":r.returncode==2 and "UNRECOVERABLE" in r.stderr})

write_json(EVIDENCE / "check.json", {"schema_version":1,"resource_id":"menhir","success":all(c["pass"] for c in cases),"versions":versions,"case_count":len(cases),"passed":sum(c["pass"] for c in cases),"cases":cases,"commands":records,"prefix":str(prefix),"network":"No downloads or package solver invoked; caller controls network enforcement","claims":{"code_backend":True,"table_backend":True,"conflict_explanation":True,"incremental_recovery":True,"all_upstream_tests":False,"coq_backend":False,"source_build_evidence":"Separate build.json; these checks alone do not establish source-build provenance."}})
if not all(c["pass"] for c in cases):
    raise SystemExit("CHECK_FAILED: " + repr([c["id"] for c in cases if not c["pass"]]))
print("CHECK_PASS",len(cases),"/",len(cases))
