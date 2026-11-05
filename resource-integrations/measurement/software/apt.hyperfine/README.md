# apt.hyperfine measurement integration

This adapter consumes output associated with the existing `apt.hyperfine`
definition, version `1.18.0-2build1`, build `2`. The canonical
package definition is `packages/apt.hyperfine/package.json` at repository root.

## Input contract

Use --export-json with an explicit shell policy and preserve warmup commands. Every time must have a matching zero exit code. A failure accepted by --ignore-failure is rejected here. Zero or negative shell-corrected times need a longer workload instead of a derived ratio.

The parser is `parse_hyperfine` in the shared `src/measurement_reuse.py`.
Its 4 software-specific format tests use synthetic contracts;
they do not establish an installed software execution or a performance result.
See `integration.json` for exact test names and shared-code references.

## Reference material and examples

`source-lock.json` fixes every retained reference file's bytes and SHA-256,
records its original URL and retains failed URL attempts separately. Reference
licenses are `MIT OR Apache-2.0`; the complete associated notices are in
`reference/`. Examples are source entry points for a separately verified installed
package and remain unexecuted in the adapter validation.

This integration creates no software artifact and changes no existing package
identity or qualification. Downloads belong to the canonical software package
and its recorded package method.
