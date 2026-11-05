#!/usr/bin/env python3
"""Validate ripgrep JSON matches, ignore handling, PCRE2 and exit distinctions."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def validate_match_stream(records):
    matches = [row["data"] for row in records if row["type"] == "match"]
    if len(matches) != 2:
        raise ValueError("Expected exactly two source matches")
    got = {(row["path"]["text"], row["line_number"], row["submatches"][0]["match"]["text"]) for row in matches}
    if got != {("visible.c", 1, "needle 42"), ("sub/nested.c", 2, "needle 73")}:
        raise ValueError("Match path, line number or substring differs")
    summaries = [row["data"] for row in records if row["type"] == "summary"]
    if len(summaries) != 1 or summaries[0]["stats"]["matches"] != 2 or summaries[0]["stats"]["matched_lines"] != 2:
        raise ValueError("The JSON summary disagrees with the actual matches")


def qualify(args, evidence):
    launcher = [str(args.tool)]
    if args.loader:
        if not args.library_path:
            raise ValueError("A private loader requires its matching private library path")
        launcher = [str(args.loader), "--library-path", args.library_path, str(args.tool)]
    commands = evidence.setdefault("commands", [])

    def run(arguments, cwd=None, expected=0):
        argv = launcher + ["--no-config", "--no-ignore-global", "--no-ignore-parent"] + arguments
        environment = dict(os.environ, LC_ALL="C")
        environment.pop("RIPGREP_CONFIG_PATH", None)
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=20, env=environment, check=False)
        commands.append({"argv": argv, "cwd": str(cwd) if cwd else None, "returncode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != expected:
            raise ValueError(f"Expected ripgrep exit {expected}; observed {result.returncode}")
        return result

    version = run(["--version"]).stdout
    if not version.startswith("ripgrep " + args.expected_version + "\n"):
        raise ValueError("The selected ripgrep version differs")
    if args.version_only:
        return {"status": "passed", "check": "upstream-version", "version_output": version, **evidence}
    with tempfile.TemporaryDirectory(prefix="cpg-ripgrep-") as directory:
        root = Path(directory)
        (root / "sub").mkdir()
        (root / ".git").mkdir()
        (root / ".gitignore").write_text("ignored.c\n")
        (root / "visible.c").write_text("needle 42\nno match here\n")
        (root / "sub/nested.c").write_text("first line\nneedle 73\n")
        (root / "ignored.c").write_text("needle 99\n")
        (root / ".hidden.c").write_text("needle 88\n")
        (root / "binary.dat").write_bytes(b"\0needle 66\n")
        result = run(["--json", "--sort", "path", "needle [0-9]+"], cwd=root)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        validate_match_stream(records)
        pcre = run(["--pcre2", "--only-matching", "--no-filename", r"(?<=needle )\d+", "visible.c"], cwd=root)
        if pcre.stdout != "42\n":
            raise ValueError("The separately linked PCRE2 lookbehind did not work")
        explicit = run(["--hidden", "--no-ignore", "--files-with-matches", "--sort", "path", "--glob", "*.c", "needle"], cwd=root)
        if explicit.stdout.splitlines() != [".hidden.c", "ignored.c", "sub/nested.c", "visible.c"]:
            raise ValueError("Explicit hidden/ignored-file inclusion differs")
        missing = run(["--no-messages", "pattern-not-present", "visible.c"], cwd=root, expected=1)
        invalid = run(["[", "visible.c"], cwd=root, expected=2)
        if missing.stdout or not invalid.stderr:
            raise ValueError("No-match and invalid-regex results were not distinguished")
    return {"status": "passed", "check": "json-search-ignore-pcre2-and-exits", "version_output": version,
            "json_records": records, **evidence,
            "scope": "Actual text search, JSON result structure, gitignore/hidden overrides, PCRE2 and exit 0/1/2 semantics; not every encoding or regex engine feature."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", type=Path, default=Path("/usr/bin/rg"))
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--library-path")
    parser.add_argument("--expected-version", default="14.1.0")
    parser.add_argument("--version-only", action="store_true")
    evidence = {}
    try:
        result = qualify(parser.parse_args(), evidence)
    except Exception as error:
        result = {"status": "failed", "reason": str(error), "error_type": type(error).__name__, **evidence}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
