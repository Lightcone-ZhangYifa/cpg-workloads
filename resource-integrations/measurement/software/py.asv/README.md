# py.asv measurement integration

This adapter consumes output associated with the existing `py.asv`
definition, version `0.6.6`, build `2`. The canonical
package definition is `packages/py.asv/package.json` at repository root.

## Input contract

Require raw samples, an unchanged benchmark version and parameter grid, and explicit time/seconds units. Summary-only results and track values do not establish timings. The local ASV example uses an existing environment and needs an explicitly selected project Git checkout.

The parser is `parse_asv` in the shared `src/measurement_reuse.py`.
Its 8 software-specific format tests use synthetic contracts;
they do not establish an installed software execution or a performance result.
See `integration.json` for exact test names and shared-code references.

## Reference material and examples

`source-lock.json` fixes every retained reference file's bytes and SHA-256,
records its original URL and retains failed URL attempts separately. Reference
licenses are `BSD-3-Clause`; the complete associated notices are in
`reference/`. Examples are source entry points for a separately verified installed
package and remain unexecuted in the adapter validation.

This integration creates no software artifact and changes no existing package
identity or qualification. Downloads belong to the canonical software package
and its recorded package method.
