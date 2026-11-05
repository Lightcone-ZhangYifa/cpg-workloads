# Measurement integrations

These integrations let experiments consume the output of five existing software
packages. The shared Python implementation validates raw samples, retains source
identities and provides balanced paired command execution. Each software entry
contains its own interface contract, examples, reference locks and verification
mapping.

| Software | Pinned version | Accepted input | Integration |
| --- | --- | --- | --- |
| `py.asv` | `0.6.6` | Result schema 2 plus the matching benchmark catalog | [ASV](software/py.asv/README.md) |
| `google-benchmark` | `v1.10.0` | JSON iteration rows with explicit time units | [Google Benchmark](software/google-benchmark/README.md) |
| `apt.hyperfine` | `1.18.0-2build1` | Raw `times` and matching successful `exit_codes` | [hyperfine](software/apt.hyperfine/README.md) |
| `py.pyperf` | `2.10.0` | JSON 1.0 with calibration and warmups separated | [pyperf](software/py.pyperf/README.md) |
| `apt.time` | `1.9-0.2build1` | One fixed-format TSV record per process | [GNU time](software/apt.time/README.md) |

The existing `packages/<software-id>/package.json` files remain authoritative for
installation, dependencies, target, source identities and package methods. This
directory supplies reusable source integrations and generates no replacement
software packages or additional resource IDs. Downloads and installation belong
to each canonical software package and its independently recorded artifact type.

## Use the shared adapter

Python 3.10 or newer is sufficient for the adapter. It uses the standard library.
From this directory:

```bash
python3 -B src/measurement_reuse.py normalize google-benchmark results.json
python3 -B src/measurement_reuse.py normalize apt.hyperfine results.json
python3 -B src/measurement_reuse.py normalize py.pyperf results.json
python3 -B src/measurement_reuse.py normalize py.asv results.json --catalog benchmarks.json
python3 -B src/measurement_reuse.py normalize apt.time process-time.tsv
```

The API also exposes the individual `parse_*` functions, `paired_plan`,
`host_state` and `run_pairs`. Original input bytes are read once for parsing and
SHA-256. Normalized records retain source and catalog identities, raw sample
indices, units and metadata. Aggregate statistics, failed commands and calibration
values cannot substitute for accepted timing samples.

## Paired command execution

`run_pairs` requires argument arrays, absolute executable paths and a declared
expected stdout SHA-256. It balances candidate order across randomized blocks,
records command output and host state, and rejects errors, wrong output, timeouts
and unexpected descendants. Cleanup applies to each owned Linux process group;
detached sessions require the surrounding target lifecycle to provide containment.

The example in `examples/pair_workload.py` compares two Python implementations of
the same exact integer sum. Its oracle checks correctness on each invocation.
The observed process times verify integration behavior; they establish no compiler
optimization result, benchmark score or performance improvement.

## Reproduce verification

Use a new output directory:

```bash
python3 -B tests/test_measurement_reuse.py
python3 -B validate.py --output /absolute/new/measurement-validation
```

There are 42 contract tests. `validate.py` runs the suite in optimized Python mode,
then executes six balanced paired blocks with 12 measured invocations. It also
checks wrong output, timeout and background-process rejection. The contract suite
includes interruption cleanup, unrelated-process survival, malformed formats and
unit or sample-boundary failures.

Per-software evidence and current shared-run evidence live in
`catalog/evidence/measurement/` at repository root. Format fixtures are synthetic.
None of the five upstream software tools is installed or executed by these checks,
and the software examples remain unexecuted. Existing software qualifications and
the historical 1,862-resource count remain unchanged.

## Source references and licensing

Each software directory has a `source-lock.json` and a `reference/` directory.
Locks preserve the exact retained bytes, original URLs and associated source
archive identities where available. Failed retrieval attempts remain explicitly
failed entries and are not treated as supplied files.

GNU time's exact 1.9 Texinfo is retained separately from the supplementary live
manual that describes 1.10. The latter contains the full GFDL terms and does not
change the pinned software version. See [SOURCE-NOTICE.txt](SOURCE-NOTICE.txt) for
the reference licenses. Authored examples and integration code follow the
repository license.
