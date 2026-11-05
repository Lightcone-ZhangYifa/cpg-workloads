# Worker 035 migration review

This directory is the unpacked master for the worker 035 measurement-tool reuse
integration. The original delivery was `cpg-20261101-worker-035-delta-v001.zip`.
Its unchanged inventory manifests are retained under `provenance/`; those hashes
describe the original ZIP, not the two source files repaired during this migration.
`current-inventory.json` describes the current master. The original README, summary
and evidence remain historical records.

## Repairs and validation

The pyperf parser now accepts a legal zero-valued warmup without adding warmups
to measured samples. Zero measured values remain rejected. Interrupted demo
commands now clean up only their own process group, retain the interrupted
invocation and report, and re-raise KeyboardInterrupt or SystemExit. The regression
uses real signals, owned parent/child processes and an unrelated sentinel process.

The original 39 checks passed. The repaired 42 checks passed in ordinary Python
and in Python optimized mode. The replay also completed 6 paired blocks and
12 timed Python invocations and rejected wrong output, timeout and a surviving
background descendant. All five retained original package definitions pass the
current CPG 1.0.0 schema without modification.

Run the repaired integration from this directory:

```sh
python3 validate.py --output /absolute/new/worker035-validation
```

The code remains a standalone integration fixture. It does not replace CPG's
executor, target lifecycle, official Benchmark protocol or installation manager.
It does not claim cleanup of descendants that deliberately create a new session.
The historical `audit_existing.py` intentionally retains its CPG 0.21.14 binding.

## Qualification and publication

This worker reuses five existing resources and provides no new resource IDs or
CPG package archives. No upstream measurement tool was installed or rerun here.
No resource, Dataset, official benchmark, hardware or performance qualification
is added. The original three functional and two trusted-APT statuses are retained
only as historical evidence. No Release asset is applicable to this source-only
integration, and the root package manifest is unchanged.

The migration receipt and original-to-current patch are in
`catalog/workers/035.json` and `catalog/workers/evidence/035/` at repository root.
