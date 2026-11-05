#!/usr/bin/env python3
"""Future host-subset functional check; authored during static review, not run here."""
import argparse
import bz2
import json
import os
from pathlib import Path
import subprocess
import tempfile


LEXER = r'''%option noyywrap
%{
#include <stdio.h>
%}
%%
[0-9]+       { puts("CPG_DIGITS"); }
[a-zA-Z]+    { puts("CPG_WORD"); }
[ \t\r\n]+  ;
.            { puts("CPG_OTHER"); }
%%
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--flex", required=True, choices=("csibe-flex", "csibe-flex-repro"))
    parser.add_argument("--bzip2", action="store_true")
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    env = dict(os.environ, LC_ALL="C")
    results = []
    with tempfile.TemporaryDirectory(prefix="cpg-csibe-check-") as folder:
        work = Path(folder)
        lexer, generated = work / "sample.l", work / "sample.c"
        lexer.write_text(LEXER)
        result = subprocess.run([str(prefix / "bin" / args.flex), "-o", str(generated), str(lexer)],
                                cwd=work, env=env, capture_output=True, timeout=10)
        if result.returncode != 0 or not generated.is_file():
            raise RuntimeError("Packaged flex did not translate the lexical grammar")
        source = generated.read_text(errors="strict")
        if not all(marker in source for marker in ("yylex", "yy_accept", "CPG_DIGITS", "CPG_WORD", "CPG_OTHER")):
            raise RuntimeError("Generated scanner lacks its state table or specified actions")
        invalid = work / "invalid.l"
        invalid.write_text("%%\n[unterminated  ECHO;\n%%\n")
        rejected = subprocess.run([str(prefix / "bin" / args.flex), "-o", str(work / "invalid.c"), str(invalid)],
                                  cwd=work, env=env, capture_output=True, timeout=10)
        if rejected.returncode == 0:
            raise RuntimeError("Packaged flex accepted a malformed character class")
        results.append("flex_grammar_translation_and_error_rejection")
        if args.bzip2:
            original = bytes(range(256)) * 8 + b"CPG compression roundtrip\n" * 64
            executable = str(prefix / "bin" / "csibe-bzip2")
            compressed = subprocess.run([executable, "-c"], input=original, cwd=work, env=env,
                                        capture_output=True, timeout=10)
            if compressed.returncode != 0 or not compressed.stdout.startswith(b"BZh"):
                raise RuntimeError("Packaged bzip2 did not produce a bzip2 stream")
            if bz2.decompress(compressed.stdout) != original:
                raise RuntimeError("Independent decoder rejected packaged bzip2 output")
            restored = subprocess.run([executable, "-d", "-c"], input=compressed.stdout, cwd=work, env=env,
                                      capture_output=True, timeout=10)
            if restored.returncode != 0 or restored.stdout != original:
                raise RuntimeError("Packaged bzip2 did not restore the exact original input")
            results.append("bzip2_independent_decode_and_native_roundtrip")
    print(json.dumps({"status": "passed", "scope": "selected_host_native_tools", "checks": results}))


if __name__ == "__main__":
    main()
