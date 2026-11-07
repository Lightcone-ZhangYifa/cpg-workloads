#!/usr/bin/env python3
"""Independent, offline black-box checks for the CPG Megaparsec frontend.

Expectations come from cpg-let-v1 and Megaparsec's documented position contract,
not from snapshots of the executable under test. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


def decode_object(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(value, dict):
        raise ValueError("stdout is not a JSON object")
    return value


class Checks:
    def __init__(self, binary: Path):
        self.binary = binary
        self.records = []
        self.assertions = 0

    def require(self, condition, message):
        self.assertions += 1
        if not condition:
            raise AssertionError(message)

    def equal(self, actual, expected, message):
        self.require(actual == expected, f"{message}: expected {expected!r}, got {actual!r}")

    def invoke(self, name, data, args, expected_code, validator, *, cwd=None, executable=None):
        command = [str(executable or self.binary), *args]
        record = {"id": name, "argv": command, "expected_returncode": expected_code,
                  "input_sha256": hashlib.sha256(data).hexdigest()}
        before = self.assertions
        started = time.monotonic()
        try:
            proc = subprocess.run(command, input=data, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=10, cwd=cwd, check=False)
            record.update(returncode=proc.returncode,
                          stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),
                          stderr=proc.stderr.decode("utf-8", "backslashreplace"))
            self.equal(proc.returncode, expected_code, "exit code")
            self.equal(proc.stderr, b"", "stderr should remain empty")
            self.require(proc.stdout.endswith(b"\n"), "JSON output must end with newline")
            actual = decode_object(proc.stdout)
            record["actual"] = actual
            validator(actual)
            record["status"] = "passed"
        except (AssertionError, ValueError, OSError, subprocess.TimeoutExpired, KeyError, TypeError, IndexError) as exc:
            record.update(status="failed", failure=f"{type(exc).__name__}: {exc}")
        record["assertion_count"] = self.assertions - before
        record["elapsed_seconds"] = round(time.monotonic() - started, 6)
        self.records.append(record)

    def header(self, obj, source, name, ok, recover=False):
        self.equal(obj["schema_version"], 1, "schema")
        self.equal(obj["megaparsec_version"], "9.8.3", "upstream version")
        self.equal(obj["language"], "cpg-let-v1", "language")
        self.equal(obj["ok"], ok, "parse status")
        self.equal(obj["recovery_requested"], recover, "recovery status")
        expected = {
            "name": name, "encoding": "UTF-8", "offset_unit": "unicode_codepoint",
            "byte_offset_unit": "utf8_byte", "utf16_offset_unit": "utf16_codeunit",
            "column_unit": "display_cell", "offset_base": 0, "line_column_base": 1,
            "tab_width": 8, "token_count": len(source),
            "byte_count": len(source.encode("utf-8")),
            "utf16_count": len(source.encode("utf-16-le")) // 2,
        }
        self.equal(obj["source"], expected, "source units and original input sizes")
        if ok:
            self.equal(obj["errors"], [], "successful parse has no errors")
            self.require(isinstance(obj["ast"], list), "successful AST is a list")
        else:
            self.equal(obj["ast"], None, "failed parse cannot advertise a valid AST")
            self.require(isinstance(obj["errors"], list) and bool(obj["errors"]), "failed parse has errors")
            self.require(isinstance(obj["pretty"], str) and bool(obj["pretty"]), "human-readable error bundle retained")

    def point(self, actual, expected, name):
        # The tuple is (Char offset, UTF-8 byte offset, UTF-16 offset, line, display column).
        offset, byte_offset, utf16_offset, line, column = expected
        self.equal(actual, {"offset": offset, "byte_offset": byte_offset,
                            "utf16_offset": utf16_offset, "source_name": name,
                            "line": line, "column": column}, "source point")

    def ascii_span(self, actual, start, end, name):
        self.equal(actual["end_exclusive"], True, "span uses exclusive end")
        self.point(actual["start"], (start, start, start, 1, start + 1), name)
        self.point(actual["end"], (end, end, end, 1, end + 1), name)

    def trivial(self, obj, source, name, position, *, unexpected, expected_contains=(), recover=False):
        self.header(obj, source, name, False, recover)
        self.equal(len(obj["errors"]), 1, "one parse error")
        error = obj["errors"][0]
        self.equal(error["kind"], "TrivialError", "actual error constructor")
        self.equal(error["offset"], position[0], "error offset")
        self.point(error["position"], position, name)
        self.equal(error["unexpected"], unexpected, "typed unexpected item")
        self.require(isinstance(error["expected"], list), "expected items remain a collection")
        for item in expected_contains:
            self.require(item in error["expected"], f"expected item not preserved: {item!r}")
        self.require(isinstance(error["message"], str), "error display remains additional text")

    def custom(self, obj, source, name, position, diagnostic):
        self.header(obj, source, name, False)
        self.equal(len(obj["errors"]), 1, "one custom error")
        error = obj["errors"][0]
        self.equal(error["kind"], "FancyError", "fancy error constructor")
        self.equal(error["offset"], position[0], "anchored custom error offset")
        self.point(error["position"], position, name)
        self.equal(error["details"], [{"kind": "ErrorCustom", "diagnostic": diagnostic}],
                   "typed custom payload, including exact decimal strings")

    def input_error(self, obj, code):
        self.equal(obj["schema_version"], 1, "input error schema")
        self.equal(obj["ok"], False, "input error status")
        self.equal(obj["kind"], "InputError", "input error type")
        self.equal(obj["code"], code, "input error code")
        self.require(isinstance(obj["message"], str) and bool(obj["message"]), "input error explains failure")


def tree(value):
    """Keep semantic AST fields; source spans are checked separately."""
    if isinstance(value, dict):
        return {k: tree(v) for k, v in value.items() if k not in ("span", "operator_span", "name_span")}
    if isinstance(value, list):
        return [tree(item) for item in value]
    return value


def integer(value, raw=None):
    return {"kind": "IntegerLiteral", "lexeme": str(value) if raw is None else raw, "value": value}


def binary(op, left, right):
    return {"kind": "Binary", "operator": op, "left": left, "right": right}


def unary(op, operand):
    return {"kind": "Unary", "operator": op, "operand": operand}


def run_checks(checks: Checks, minimal: bool, encoder_probe: Path | None):
    c = checks
    tokens = lambda value: {"kind": "Tokens", "tokens": value}
    label = lambda value: {"kind": "Label", "label": value}
    eof = {"kind": "EndOfInput"}

    def parse_case(case_id, source, validate, expected_code=0, name="fixture.cpg", recover=False, args=None):
        flags = ["--source-name", name] + (["--recover"] if recover else [])
        c.invoke(case_id, source.encode("utf-8"), flags if args is None else args,
                 expected_code, validate)

    def version(obj):
        c.equal(obj["name"], "cpg-megaparsec-frontend", "binary identity")
        c.equal(obj["schema_version"], 1, "version schema")
        c.equal(obj["megaparsec_version"], "9.8.3", "reported library pin")
        c.equal(obj["language"], "cpg-let-v1", "reported language")
    c.invoke("version", b"", ["--version"], 0, version)

    source = "let x = 1 + 2 * 3;"
    def precedence(obj):
        c.header(obj, source, "precedence.cpg", True)
        c.equal(tree(obj["ast"]), [{"kind": "LetStatement", "name": "x",
                "value": binary("+", integer(1), binary("*", integer(2), integer(3)))}], "multiplication precedence")
        stmt = obj["ast"][0]
        c.ascii_span(stmt["span"], 0, 18, "precedence.cpg")
        c.ascii_span(stmt["name_span"], 4, 5, "precedence.cpg")
        add = stmt["value"]
        c.ascii_span(add["span"], 8, 17, "precedence.cpg")
        c.ascii_span(add["operator_span"], 10, 11, "precedence.cpg")
        c.ascii_span(add["left"]["span"], 8, 9, "precedence.cpg")
        multiply = add["right"]
        c.ascii_span(multiply["span"], 12, 17, "precedence.cpg")
        c.ascii_span(multiply["operator_span"], 14, 15, "precedence.cpg")
        c.ascii_span(multiply["left"]["span"], 12, 13, "precedence.cpg")
        c.ascii_span(multiply["right"]["span"], 16, 17, "precedence.cpg")
    parse_case("valid-precedence-and-all-ascii-spans", source, precedence, name="precedence.cpg")

    source = "let x = ?;"
    parse_case("typed-syntax-error", source,
        lambda o: c.trivial(o, source, "syntax.cpg", (8, 8, 8, 1, 9),
                            unexpected=tokens("?"), expected_contains=[label("expression")]),
        expected_code=1, name="syntax.cpg")

    source = "let if = 1;"
    parse_case("typed-reserved-word-error-at-token-start", source,
        lambda o: c.custom(o, source, "reserved.cpg", (4, 4, 4, 1, 5),
                           {"constructor": "ReservedIdentifier", "identifier": "if"}),
        expected_code=1, name="reserved.cpg")

    source = "/*😀*/let 中 = ?;"
    parse_case("unicode-three-distinct-offsets-and-display-column", source,
        lambda o: c.trivial(o, source, "unicode.cpg", (13, 18, 14, 1, 16),
                            unexpected=tokens("?"), expected_contains=[label("expression")]),
        expected_code=1, name="unicode.cpg")

    source = "let x = ?;\nlet y = ;\nlet z = 3;"
    def recovered(obj):
        c.header(obj, source, "recover.cpg", False, True)
        c.equal(len(obj["errors"]), 2, "recovery retains both original errors")
        for error, point, unexpected in zip(obj["errors"],
                [(8, 8, 8, 1, 9), (19, 19, 19, 2, 9)], ["?", ";"]):
            c.equal(error["kind"], "TrivialError", "recovered error kind")
            c.equal(error["offset"], point[0], "recovered error offset")
            c.point(error["position"], point, "recover.cpg")
            c.equal(error["unexpected"], tokens(unexpected), "recovered unexpected item")
    parse_case("multiple-errors-recovery-remains-failure", source, recovered,
               expected_code=1, name="recover.cpg", recover=True)

    source = "let x = 1"
    parse_case("typed-end-of-input", source,
        lambda o: c.trivial(o, source, "eof.cpg", (9, 9, 9, 1, 10),
                            unexpected=eof, expected_contains=[tokens(";")]),
        expected_code=1, name="eof.cpg")
    c.invoke("strict-invalid-utf8-rejected", b"let x = 1;\xff", [], 2,
             lambda o: c.input_error(o, "invalid_utf8"))

    if minimal:
        return

    for case_id, source, point in [
        ("ascii-tab", "let x =\t?;", (8, 8, 8, 1, 9)),
        ("cjk-before-tab", "let 中\t= ?;", (8, 10, 8, 1, 11)),
        ("combining-identifier", "let e\u0301 = ?;", (9, 10, 9, 1, 9)),
        ("crlf-and-tab", "let x = 1;\r\n\tlet y = ?;", (21, 21, 21, 2, 17)),
        ("bare-carriage-return", "let x =\r?;", (8, 8, 8, 1, 8)),
    ]:
        name = case_id + ".cpg"
        parse_case(case_id, source,
            lambda o, s=source, p=point, n=name: c.trivial(o, s, n, p,
                unexpected=tokens("?"), expected_contains=[label("expression")]),
            expected_code=1, name=name)

    source = "let x = 8 - 3 - 1;"
    def associativity(obj):
        c.header(obj, source, "associativity.cpg", True)
        c.equal(tree(obj["ast"])[0]["value"], binary("-", binary("-", integer(8), integer(3)), integer(1)),
                "binary subtraction is left associative")
    parse_case("left-associativity", source, associativity, name="associativity.cpg")

    source = "let x = --(1 + 2) * +3;"
    def nested(obj):
        c.header(obj, source, "unary.cpg", True)
        expected = binary("*", unary("-", unary("-", {"kind": "Parenthesized", "expression": binary("+", integer(1), integer(2))})), unary("+", integer(3)))
        c.equal(tree(obj["ast"])[0]["value"], expected, "unary chains and explicit parentheses")
    parse_case("unary-and-parenthesized-tree", source, nested, name="unary.cpg")

    source = " /* outer /* inner */ end */ let x = 0007; // tail\r\n"
    def comments(obj):
        c.header(obj, source, "comments.cpg", True)
        c.equal(tree(obj["ast"]), [{"kind": "LetStatement", "name": "x", "value": integer(7, "0007")}], "comments and literal lexeme")
        start = 29
        end = 42
        c.ascii_span(obj["ast"][0]["span"], start, end, "comments.cpg")
    parse_case("nested-comments-and-trivia-excluded-from-span", source, comments, name="comments.cpg")

    source = " \t/* empty /* nested */ */\r\n// only trivia"
    def empty(obj):
        c.header(obj, source, "empty.cpg", True)
        c.equal(obj["ast"], [], "empty grammar accepts trivia only")
    parse_case("trivia-only-program", source, empty, name="empty.cpg")

    source = "let e\u0301 = 7; let é = 8;"
    def distinct_unicode_names(obj):
        c.header(obj, source, "names.cpg", True)
        c.equal([s["name"] for s in obj["ast"]], ["e\u0301", "é"], "identifier spelling is not normalized")
        c.point(obj["ast"][0]["name_span"]["start"], (4, 4, 4, 1, 5), "names.cpg")
        c.point(obj["ast"][0]["name_span"]["end"], (6, 7, 6, 1, 6), "names.cpg")
    parse_case("identifier-normalization-is-not-silently-applied", source, distinct_unicode_names, name="names.cpg")

    source = "let letx = 2147483647;"
    def max_value(obj):
        c.header(obj, source, "maximum.cpg", True)
        c.equal(tree(obj["ast"]), [{"kind": "LetStatement", "name": "letx", "value": integer(2147483647)}],
                "maximum and longest keyword boundary")
    parse_case("integer-maximum-and-keyword-prefix-identifier", source, max_value, name="maximum.cpg")

    for case_id, literal, prefix in [
        ("integer-above-bound", "2147483648", "let x = "),
        ("leading-zero-range-diagnostic", "0002147483648", "let x = "),
        ("huge-integer-preserves-decimal", "9" * 80, "let x = "),
        ("unary-minus-does-not-expand-token-domain", "2147483648", "let x = -"),
    ]:
        source = prefix + literal + ";"
        offset = len(prefix)
        diagnostic = {"constructor": "IntegerOutOfRange", "lexeme": literal,
                      "value_decimal": str(int(literal)), "maximum_decimal": "2147483647"}
        parse_case(case_id, source,
            lambda o, s=source, p=offset, d=diagnostic: c.custom(o, s, "range.cpg", (p, p, p, 1, p + 1), d),
            expected_code=1, name="range.cpg")

    source = "let x = 12abc;"
    parse_case("integer-token-boundary", source,
        lambda o: c.trivial(o, source, "boundary.cpg", (10, 10, 10, 1, 11),
                            unexpected=tokens("a"), expected_contains=[label("integer token boundary")]),
        expected_code=1, name="boundary.cpg")

    source = "let x = ?"
    parse_case("recovery-at-eof-terminates", source,
        lambda o: c.trivial(o, source, "recover-eof.cpg", (8, 8, 8, 1, 9),
                            unexpected=tokens("?"), recover=True),
        expected_code=1, name="recover-eof.cpg", recover=True)

    source = "/*"
    parse_case("recovery-of-unterminated-leading-comment", source,
        lambda o: c.trivial(o, source, "comment-eof.cpg", (2, 2, 2, 1, 3),
                            unexpected=eof, recover=True),
        expected_code=1, name="comment-eof.cpg", recover=True)

    source = "let x = 1;"
    escaped_name = 'quoted"\\source\nname.cpg'
    parse_case("source-name-json-escaping", source,
        lambda o: (c.header(o, source, escaped_name, True),
                   c.point(o["ast"][0]["span"]["start"], (0, 0, 0, 1, 1), escaped_name)),
        name=escaped_name)

    c.invoke("invalid-arguments-exit-2", b"", ["--unknown"], 2, lambda o: c.input_error(o, "invalid_arguments"))
    c.invoke("missing-source-name-exit-2", b"", ["--source-name"], 2, lambda o: c.input_error(o, "invalid_arguments"))
    c.invoke("overlong-utf8-rejected", b"\xc0\xaf", [], 2, lambda o: c.input_error(o, "invalid_utf8"))

    with tempfile.TemporaryDirectory(prefix="cpg-megaparsec-check-") as directory:
        directory = Path(directory)
        file_source = "let x = 1;\r\nlet y = 2;"
        path = directory / "source.cpg"
        path.write_bytes(file_source.encode("utf-8"))
        def from_file(obj):
            c.header(obj, file_source, str(path), True)
            c.equal(len(obj["ast"]), 2, "file contains two statements")
            c.point(obj["ast"][1]["span"]["start"], (12, 12, 12, 2, 1), str(path))
        c.invoke("file-input-preserves-crlf", b"", [str(path)], 0, from_file)
        dash = directory / "-dash.cpg"
        dash.write_bytes(b"let x = 1;")
        c.invoke("dash-prefixed-filename", b"", ["--", "-dash.cpg"], 0,
                 lambda o: c.header(o, "let x = 1;", "-dash.cpg", True), cwd=directory)
        missing = directory / "does-not-exist.cpg"
        c.invoke("missing-file-exit-2", b"", [str(missing)], 2, lambda o: c.input_error(o, "io_error"))

    if encoder_probe is not None:
        def variants(obj):
            trivial = obj["trivial"]["errors"][0]
            c.equal(trivial["kind"], "TrivialError", "probe trivial constructor")
            c.equal(trivial["unexpected"], None, "optional unexpected remains null")
            c.equal(trivial["expected"], [tokens("xy"), label("identifier"), eof], "all expected constructors remain distinct")
            c.point(trivial["position"], (1, 1, 1, 1, 2), "variants.cpg")
            fancy = obj["fancy"]["errors"][0]
            c.equal(fancy["kind"], "FancyError", "probe fancy constructor")
            c.equal(fancy["details"], [
                {"kind": "ErrorFail", "message": "deliberate\n\u0000failure"},
                {"kind": "ErrorIndentation", "ordering": "LT", "reference": 3, "actual": 5},
                {"kind": "ErrorCustom", "diagnostic": {"constructor": "ReservedIdentifier", "identifier": "let"}},
            ], "all fancy encoder variants preserve constructors and payloads")
            c.point(fancy["position"], (1, 1, 1, 1, 2), "variants.cpg")
        c.invoke("library-json-all-error-constructors", b"", [], 0, variants, executable=encoder_probe)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--minimal", action="store_true", help="eight high-value installation checks")
    parser.add_argument("--encoder-probe", type=Path, help="optional independently compiled JsonVariantsProbe")
    args = parser.parse_args()
    try:
        binary_path = args.binary.resolve(strict=True)
        if not binary_path.is_file():
            raise ValueError("binary must be a regular file")
        if args.report and args.report.exists():
            raise ValueError("report already exists; choose a fresh output path")
        encoder = args.encoder_probe.resolve(strict=True) if args.encoder_probe else None
        started = time.monotonic()
        checks = Checks(binary_path)
        run_checks(checks, args.minimal, encoder)
        failed = [r["id"] for r in checks.records if r["status"] != "passed"]
        report = {
            "schema_version": 1, "status": "failed" if failed else "passed",
            "mode": "minimal" if args.minimal else "full", "case_count": len(checks.records),
            "assertion_count": checks.assertions, "failed_checks": failed,
            "binary": str(binary_path), "binary_sha256": hashlib.sha256(binary_path.read_bytes()).hexdigest(),
            "encoder_probe": str(encoder) if encoder else None,
            "encoder_probe_sha256": hashlib.sha256(encoder.read_bytes()).hexdigest() if encoder else None,
            "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "platform": platform.platform(), "python": platform.python_version(),
            "expectation_basis": "independent cpg-let-v1 grammar and pinned Megaparsec 9.8.3 public API/source; no learned snapshots",
            "checks": checks.records,
        }
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            with args.report.open("x", encoding="utf-8") as handle:
                handle.write(output)
        print(output, end="")
        return 1 if failed else 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "failed", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
