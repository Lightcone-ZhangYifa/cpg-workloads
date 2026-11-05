# google-benchmark measurement integration

This adapter consumes output associated with the existing `google-benchmark`
definition, version `v1.10.0`, build `2`. The canonical
package definition is `packages/google-benchmark/package.json` at repository root.

## Input contract

Accept raw iteration rows and convert ns/us/ms/s explicitly. Aggregate rows cannot add samples, and real_time is already per iteration. The example checks its checksum outside timing and exercises empty and nonempty inputs; it has not been compiled or run by these adapter checks.

The parser is `parse_google_benchmark` in the shared `src/measurement_reuse.py`.
Its 7 software-specific format tests use synthetic contracts;
they do not establish an installed software execution or a performance result.
See `integration.json` for exact test names and shared-code references.

## Reference material and examples

`source-lock.json` fixes every retained reference file's bytes and SHA-256,
records its original URL and retains failed URL attempts separately. Reference
licenses are `Apache-2.0`; the complete associated notices are in
`reference/`. Examples are source entry points for a separately verified installed
package and remain unexecuted in the adapter validation.

This integration creates no software artifact and changes no existing package
identity or qualification. Downloads belong to the canonical software package
and its recorded package method.
