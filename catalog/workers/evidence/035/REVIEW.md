# Worker 035 migration review

This is a five-resource reuse integration, with no new CPG package or release artifact. Keep it under `resource-integrations/workers/035`. It does not modify the framework package manager, Experiment, Trainer, or runtime catalog.

All 76 original files were inspected for integrity before edits: 75 delivery-manifest entries and 74 file-manifest entries match bytes, SHA-256, and mode. The original 39-test suite and original `validate.py` both passed.

## Repairs

1. pyperf 2.10.0 explicitly allows warmup values equal to zero (`source-reference/pyperf-api.rst`, Run contract), while formal measured values must remain strictly positive. The adapter previously rejected valid zero warmups. It now preserves them without admitting them into timing samples. A positive and negative regression preserve this distinction; the valid-input failure was reproduced before the fix.
2. KeyboardInterrupt and SystemExit during an owned invocation now use bounded process-group termination/collection, record cleanup and raw output, and re-raise the original control exception after recording the invocation. The final report remains rejected. A real-signal regression waits for a live child and descendant, sends SIGINT or SIGUSR1 to the test process, verifies that the owned group no longer exists and its rejection evidence is retained, and verifies that an unrelated process remains alive. SystemExit code 23 is preserved.

Exactly two files changed; `migration-fixes.patch` and `modified-files.json` compare their current bytes directly against the downloaded ZIP. Original definitions, historical results, evidence, reference documents, licenses, and original manifests remain unchanged. Move original manifests to provenance if the integration's current inventory is stored beside the repaired code; do not describe their original hashes as current hashes.

## Final validation

42 tests pass in normal mode and 42 pass in Python optimized mode through `validate.py`. The complete validator also successfully runs 6 paired blocks / 12 timed Python invocations and rejects incorrect output, timeout, and unexpected background descendants. The test logs retain the additional real-interruption regression. Upstream tool executions, upstream installs, formal qualification changes, new resource IDs, and publishable CPG artifacts are all zero.

## Boundaries

The five upstream tools were not installed or executed. Format fixtures are synthetic. The original 3 functional / 2 trusted APT records remain historical evidence. `audit_existing.py` intentionally binds 0.21.14; this review does not weaken that guard or replace it with a same-name/new-version assumption. The helper owns a process group, not detached process sessions or formal CPG target lifecycle. No performance significance or speedup qualification is asserted.
