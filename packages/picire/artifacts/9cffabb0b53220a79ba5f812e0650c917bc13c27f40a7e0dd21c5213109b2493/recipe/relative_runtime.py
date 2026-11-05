#!/usr/bin/env python3
"""Replace installation-local Python shebangs with relative installed launchers.

The generated Python bodies are retained byte-for-byte below runtime/libexec.
The runtime still uses the exact recorded base interpreter and its standard
library. This is an application interface profile, not a general relocatable
virtualenv or cross-ABI Python distribution.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "assets", "prefix", "build"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    runtime, share = prefix / "runtime", prefix / "share/picire"
    programs = runtime / "libexec/cpg-entrypoints"
    programs.mkdir(parents=True)
    originals = share / "relocation/original-entrypoints"
    originals.mkdir(parents=True)
    changed = {}
    entries = []
    for script in sorted((runtime / "bin").iterdir()):
        if not script.is_file() or script.is_symlink():
            continue
        content = script.read_bytes()
        first, separator, body = content.partition(b"\n")
        if not first.startswith(b"#!") or b"python" not in first:
            continue
        need(str(runtime).encode() in first, "Unexpected Python entry point interpreter: " + str(script))
        need(re.fullmatch(r"[A-Za-z0-9_.+-]+", script.name), "Unsafe entry point name")
        shutil.copy2(script, originals / script.name)
        original_sha = hashlib.sha256(content).hexdigest()
        program = programs / script.name
        program.write_bytes(body)
        program.chmod(0o644)
        launcher = ("#!/bin/sh\n"
                    "here=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
                    "exec \"$here/python\" -I -B \"$here/../libexec/cpg-entrypoints/" + script.name + "\" \"$@\"\n")
        script.write_text(launcher)
        script.chmod(0o755)
        changed[script.resolve()] = (script.read_bytes(), program)
        entries.append({"name": script.name, "original_sha256": original_sha, "original_shebang": first.decode(),
                        "launcher_sha256": sha(script), "program_sha256": sha(program),
                        "python_body_unchanged": program.read_bytes() == body})
    need(entries and any(row["name"] == "picire" for row in entries), "No installed Picire entry point was rewritten")
    # Keep the installed distributions' RECORD metadata consistent with the
    # changed launcher bytes; the retained original wheel itself is unchanged.
    record_updates = []
    for record in sorted(runtime.glob("lib/python*/site-packages/*.dist-info/RECORD")):
        rows = list(csv.reader(io.StringIO(record.read_text())))
        touched = []
        for row in rows:
            if not row:
                continue
            installed = (record.parent.parent / row[0]).resolve()
            if installed in changed:
                content, _ = changed[installed]
                row[1] = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
                row[2] = str(len(content))
                touched.append(installed.relative_to(runtime).as_posix())
        if touched:
            before = sha(record)
            with record.open("w", newline="") as stream:
                csv.writer(stream, lineterminator="\n").writerows(rows)
            record_updates.append({"path": record.relative_to(runtime).as_posix(), "before_sha256": before,
                                   "after_sha256": sha(record), "changed_entrypoints": touched})
    # Remove the build-directory prefix from CPython's informational command
    # line. The actual base home and executable identity remain untouched.
    cfg = runtime / "pyvenv.cfg"
    original_cfg = cfg.read_bytes()
    (share / "relocation/original-pyvenv.cfg").write_bytes(original_cfg)
    lines = [line for line in cfg.read_text().splitlines() if not line.startswith("command = ")]
    lines.append("command = compiler-playground Picire fixed CPython 3.12 application runtime")
    cfg.write_text("\n".join(lines) + "\n")
    report = {"schema_version": 1, "status": "prepared_for_external_qualification", "entrypoints": entries,
              "record_updates": record_updates, "pyvenv_cfg_before_sha256": hashlib.sha256(original_cfg).hexdigest(),
              "pyvenv_cfg_after_sha256": sha(cfg), "scope": "Explicit application and interpreter entry points only; no activation-script or cross-ABI claim"}
    (share / "relative-runtime.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    profile_path = share / "profile.json"
    profile = json.loads(profile_path.read_text())
    profile["source_rebuild_required"] = False
    profile["binary_profile"] = {"kind": "fixed-base-interpreter-and-relative-application-entrypoints",
                                 "qualification_evidence": "External replay summary must pass before admission",
                                 "generic_virtualenv_activation": "not_qualified", "other_abi_or_platform": "not_qualified",
                                 "entrypoints": len(entries), "relative_runtime_sha256": sha(share / "relative-runtime.json")}
    profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "prepared", "relative_entrypoints": len(entries), "record_updates": len(record_updates)}))


if __name__ == "__main__":
    main()
