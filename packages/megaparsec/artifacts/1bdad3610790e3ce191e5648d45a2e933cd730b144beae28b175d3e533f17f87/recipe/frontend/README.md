# CPG Megaparsec frontend fixture

This is a bounded, runnable frontend example for the CPG `worker 003` Megaparsec
resource. It demonstrates typed diagnostics, token and byte offsets, display
columns, and deterministic error recovery. It does not execute programs,
generate machine code, or certify a general compiler.

The package pins **Megaparsec 9.8.3** and exports a Haskell library module,
`CPG.Frontend`, plus the executable `cpg-megaparsec-frontend`.

## Language: `cpg-let-v1`

```text
program    := statement*
statement  := "let" identifier "=" expression ";"
expression := term with prefix +/-, then left-associative */,
              then left-associative +/-
term       := decimal_integer | identifier | "(" expression ")"
```

Whitespace and `//` line comments or nested `/* */` comments may occur between
tokens. An identifier starts with a Unicode letter or underscore, followed by
Unicode letters/numbers, underscore, or combining marks, as classified by the
pinned GHC's `Data.Char`. Its spelling is kept
exactly: no Unicode normalization is applied. The reserved spellings are `let`,
`if`, `then`, `else`, `while`, `return`, `true`, and `false`.

Decimal literal tokens use ASCII digits and must be in `[0, 2147483647]`.
This is a bound on the **unsigned token**, before unary signs: `-2147483648`
therefore reports `IntegerOutOfRange`. The fixture does not claim signed-32-bit
expression semantics. Leading zeroes are accepted and retained in `lexeme`.
Variable binding, arithmetic overflow, division by zero, and type checking are
outside the grammar's scope.

Magnitude is checked as decimal text before numeric conversion. Very long
out-of-range tokens remain textual diagnostics; they are not converted into
unbounded-size integers merely to reject them. Accepted numeric conversion
operates on at most ten significant digits. Source/diagnostic size still grows
with the input; the fixture does not promise a fixed memory bound.

## Command line

```bash
cpg-megaparsec-frontend examples/valid.cpg
cpg-megaparsec-frontend --source-name example.cpg < examples/invalid.cpg
cpg-megaparsec-frontend --recover examples/recover.cpg
cpg-megaparsec-frontend --version
```

Omitting the filename or specifying `-` reads stdin. `-- FILE` permits a name
starting with a dash. Bytes are decoded as strict UTF-8; CRLF is preserved and
is not converted to LF. One UTF-8 JSON object is emitted on stdout, followed by
a newline. Exit codes are **0** for a valid parse, **1** for parse errors, and
**2** for invalid UTF-8, I/O errors, or invalid arguments. `--help` emits text.

`--recover` registers the original typed error, discards characters through the
next **raw semicolon** (or EOF), and resumes. The scan consumes input unless it
is already at EOF, so a repeated failure cannot spin at the same position.
Semicolons inside malformed comments are also scan boundaries. This simple,
explicit synchronization policy is specific to the fixture. Registered errors
remain errors: recovery returns `ok: false`, `ast: null`, and exit code 1, even
when later statements parse successfully. No partial AST is presented as valid.

## Structured result

Successful results include an `ast` array. Every statement and expression has a
`span`; identifier and operator tokens have their own spans. Span ends are
exclusive and exclude trailing whitespace/comments. Parentheses remain explicit
AST nodes, and precedence is visible in nested `Unary` and `Binary` nodes.

Failure results retain the actual Megaparsec error constructors:

- `TrivialError` contains `unexpected` and ordered `expected` items tagged
  `Tokens`, `Label`, or `EndOfInput`.
- `FancyError` contains ordered details tagged `ErrorFail`, `ErrorIndentation`,
  or `ErrorCustom`.
- `ErrorCustom` retains the `ReservedIdentifier` or `IntegerOutOfRange`
  constructor and its data. Numeric custom diagnostics preserve the original
  decimal text, so a JSON consumer need not round very large numbers.
- `message` and the bundle's `pretty` text are additional human-readable views;
  they do not replace typed diagnostics.

The grammar naturally exercises `TrivialError` and both `ErrorCustom`
constructors. It does not use indentation-sensitive syntax or `fail`, so the
`ErrorIndentation` and `ErrorFail` encoder branches describe preserved API
variants, not claims that this grammar produces those errors.

### Position units

`source` declares the units for all returned points:

| Field | Meaning |
| --- | --- |
| `offset` | Zero-based count of Unicode codepoints (`Char` tokens) |
| `byte_offset` | Zero-based byte count in the original UTF-8 input |
| `utf16_offset` | Zero-based UTF-16 code-unit count from the start of the file |
| `line` | One-based line |
| `column` | One-based display-cell column from Megaparsec 9.8.3 |
| `tab_width` | 8; tabs advance to the next tab stop |

The fixture calls Megaparsec's `getSourcePos` and `reachOffsetNoLine`, including
its Unicode-width handling, rather than treating codepoint or UTF-8 counts as
columns. UTF-16 offsets are whole-file offsets, not LSP line-relative columns.
Source names remain exact strings, including quotes, backslashes, and
newlines; the JSON encoder escapes JSON control characters correctly.

## Library use

```haskell
import CPG.Frontend
import qualified Data.Text as T

let input = T.pack "let x = 1 + 2 * 3;"
let parsed = parseProgram False "example.cpg" input
putStrLn (renderJson (resultJson False "example.cpg" input parsed))
```

`ParseResult` remains `Either (ParseErrorBundle Text Diagnostic) [Statement]`:
callers can inspect the original typed bundle directly. The JSON view is only
an adapter. `resultJson` must receive the same input and source name used for
`parseProgram`, because its byte offsets are calculated from that input.

## Build boundary

The parent CPG resource supplies the pinned GHC toolchain, local package sources,
and offline build project. Use its build/installation recipe for reproducible
deployment. This Cabal package itself declares dependencies but never fetches
them. No claim about offline dependency availability follows merely from this
package's presence.
