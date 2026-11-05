# Measurement integration verification

This directory records a fresh validation of
`resource-integrations/measurement/`. Paths, software identities and test names
refer to that semantic source layout. The raw records are the output of this
execution, not rewritten historical command logs.

`review.json` summarizes the observed results and verifies that the five canonical
software definitions and the existing two APT artifact templates retained their
exact bytes. `source-inventory.json` binds the reviewed integration files to their
SHA-256, byte counts and modes.

## Executed checks

- `runs/contracts-normal.*` records all 42 contract tests in normal Python mode.
- `runs/integration-optimized.*` records the validation entry point. Its complete
  output is under `integration-run/`, including the same 42 tests in optimized
  Python mode, six paired blocks and 12 measured command invocations.
- Wrong output, timeout and unexpected background descendants are rejected in
  the recorded integration run. The contract suite additionally exercises
  interruption cleanup and survival of an unrelated process.
- `software/<id>.json` maps each software-specific parser to its actually observed
  passing format tests: ASV 8, Google Benchmark 7, hyperfine 4, pyperf 8 and GNU
  time 4. The other 11 tests cover shared input handling and command execution.

Format inputs are synthetic contracts; the real commands use a small isolated
Python sum fixture. The five upstream software tools were neither installed nor
executed. Their examples remain unexecuted. This validation changes no software
qualification, creates no finished software artifact and supports no performance
or compiler optimization claim.
