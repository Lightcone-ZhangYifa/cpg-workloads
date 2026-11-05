# py.pyperf measurement integration

This adapter consumes output associated with the existing `py.pyperf`
definition, version `2.10.0`, build `2`. The canonical
package definition is `packages/py.pyperf/package.json` at repository root.

## Input contract

Preserve warmups without counting them as samples, exclude calibration runs, and accept only time values. Values already account for loops and inner_loops. A zero warmup is valid; a zero measured value is rejected. The example requires the existing pinned package interpreter and was not executed by these adapter checks.

The parser is `parse_pyperf` in the shared `src/measurement_reuse.py`.
Its 8 software-specific format tests use synthetic contracts;
they do not establish an installed software execution or a performance result.
See `integration.json` for exact test names and shared-code references.

## Reference material and examples

`source-lock.json` fixes every retained reference file's bytes and SHA-256,
records its original URL and retains failed URL attempts separately. Reference
licenses are `MIT`; the complete associated notices are in
`reference/`. Examples are source entry points for a separately verified installed
package and remain unexecuted in the adapter validation.

This integration creates no software artifact and changes no existing package
identity or qualification. Downloads belong to the canonical software package
and its recorded package method.
