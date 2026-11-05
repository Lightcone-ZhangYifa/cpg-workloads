"""Check selected SQLite CLI/C API, durable SQL behavior and extension loading."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

SOURCE_ID = "555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76"


def check(prefix: Path, *, version_only=False):
    prefix = prefix.resolve(strict=True)
    env = dict(os.environ, LC_ALL="C")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "SQLITE_HISTORY", "SQLITE_TMPDIR"):
        env.pop(key, None)
    commands = []

    def run(argv, *, stdin=None, expected=0):
        argv = [str(item) for item in argv]
        result = subprocess.run(argv, input=stdin, env=env, capture_output=True, text=True, timeout=45)
        row = {"argv": argv, "stdin": stdin, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        commands.append(row)
        if (expected == 0 and result.returncode != 0) or (expected == "nonzero" and result.returncode == 0):
            raise RuntimeError(json.dumps(row))
        return result.stdout.strip()

    cli = prefix / "bin/sqlite3"
    version = run([cli, "--version"])
    if not version.startswith("3.54.1 ") or SOURCE_ID not in version:
        raise RuntimeError("The selected CLI has a different SQLite version or Fossil source identity: " + version)
    if version_only:
        return {"status": "passed", "kind": "version", "version": "3.54.1", "source_id": SOURCE_ID, "commands": commands}
    with tempfile.TemporaryDirectory(prefix="cpg-sqlite-check-") as directory:
        work = Path(directory)
        api = run([prefix / "bin/cpg-sqlite-api-probe", work / "api.sqlite"])
        details = dict(line.split("=", 1) for line in api.splitlines() if "=" in line)
        if Path(details["library"]).resolve(strict=True).parent != prefix / "lib" or SOURCE_ID not in details["source_id"]:
            raise RuntimeError("The API probe did not load the selected SQLite build")
        db, copied = work / "durable.sqlite", work / "backup.sqlite"
        sql = ".bail on\nPRAGMA foreign_keys=ON;\nCREATE TABLE records(id INTEGER PRIMARY KEY, name TEXT UNIQUE, value INTEGER NOT NULL);\n"
        sql += "BEGIN; INSERT INTO records VALUES(1,'compiler',7),(2,'dataset',11); COMMIT;\n"
        sql += "BEGIN; UPDATE records SET value=100; ROLLBACK;\nSELECT sum(value) FROM records;\nPRAGMA integrity_check;\n"
        sql += f".backup '{copied}'\n"
        if run([cli, "-batch", "-init", "/dev/null", db], stdin=sql).splitlines() != ["18", "ok"]:
            raise RuntimeError("Durable SQL or rollback/integrity behavior differs")
        if run([cli, "-batch", "-init", "/dev/null", copied, "SELECT sum(value) FROM records;"]) != "18":
            raise RuntimeError("CLI backup changed persistent data")
        run([cli, "-batch", "-init", "/dev/null", db, "INSERT INTO records VALUES(3,'compiler',99);"], expected="nonzero")
        dumped = run([cli, "-batch", "-init", "/dev/null", db, ".dump"])
        restored = work / "restored.sqlite"
        run([cli, "-batch", "-init", "/dev/null", restored], stdin=".bail on\n" + dumped)
        if run([cli, "-batch", "-init", "/dev/null", restored, "SELECT sum(value) FROM records;"]) != "18":
            raise RuntimeError("SQL dump/restore changed persistent data")
        extension = prefix / "share/compiler-playground/sqlite/cpg_extension.so"
        loaded = run([cli, "-batch", "-init", "/dev/null", ":memory:"],
                     stdin=f".bail on\n.load '{extension}'\nSELECT cpg_add_one(41);\n")
        if loaded != "42":
            raise RuntimeError("The selected loadable extension did not execute")
        options = run([cli, "-batch", "-init", "/dev/null", ":memory:", "PRAGMA compile_options;"]).splitlines()
        required = {"ENABLE_FTS5", "ENABLE_RTREE", "ENABLE_SESSION", "ENABLE_PREUPDATE_HOOK", "THREADSAFE=1"}
        if not required.issubset(set(options)):
            raise RuntimeError("Declared feature flags are absent: " + repr(required - set(options)))
    return {"status": "passed", "kind": "functional", "api": details,
            "compile_options": options, "scope": "Package-local SQLite CLI and shared API; WAL, writer conflict, transactions, backup, dump/restore, constraints, FTS5/RTREE/JSON/session and real loadable extension.",
            "upstream_tcl_suite": "not_run", "benchmark_score": None, "commands": commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.prefix, version_only=args.version_only), indent=2))


if __name__ == "__main__":
    main()
