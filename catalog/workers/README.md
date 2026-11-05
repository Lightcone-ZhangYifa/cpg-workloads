# Numbered worker archive queue

This directory records the explicitly assigned migration of deliveries with
numbered workers. Pre-worker deliveries remain under their existing migration
records. The worker queue does not replace or recalculate the historical
**1,862-resource denominator**.

## What the queue establishes

`archive-queue.json` is a JSON array of archive groups discovered through Library
filename and byte-size metadata on 2026-11-05. It includes primary delta archives,
support archives, checkpoints, transport tools, and acceptance or audit bundles.
Each entry retains the observed filenames, worker numbers, compressed byte
counts, and Library source IDs. It contains no local workspace paths or download
credentials.

The inventory establishes that these metadata records were visible. It does not
establish archive integrity, completeness of an original delivery, the quality of
a package, a successful build, or a published release. Classifications and split
group membership are inferred from filenames and must be checked against the
delivery index and actual contents during processing. For example, observing
parts 1 through 6 without gaps does not prove that part 6 was the final part.

Groups are ordered by the sum of their parts' compressed byte counts, with the
group filename as the tie-breaker. This sum is not an estimate of extraction or
build space. The `integrity_boundary` fields describe the evidence available when
this inventory was made; they are not the group's current validation status.

## Rolling processing

Process complete primary delta groups (`kind: primary-delta`) from smallest to
largest. Confirm the declared input set before treating a split delivery as a
complete group. Acquire only the current group and the support inputs it actually
needs. Process its inner packages one at a time, keeping extraction and build
space bounded. Agents may inspect separate portions of that group in parallel
without downloading additional outer archives.

An auxiliary bundle, checkpoint, report, or a small trailing volume is not an
independent completed worker group. Keep its provenance attached to the primary
group it supports. A missing or unavailable delivery remains recorded as such;
do not infer completion from neighboring worker numbers. A blocked group can be
recorded and deferred while the next processable group is handled.

Commit each processed group with its source changes and evidence, and push that
commit promptly. Delete only this session's reproducible temporary downloads,
extractions, and build outputs after the corresponding durable records and any
required Release assets are confirmed. Preserve unique unpublished results and
other sessions' work.

## Per-group receipts are the status record

Keep a separate receipt for each inspected group in this directory. Record the
source group filename and package identities so that the receipt can be matched
to the queue. Read current progress from those receipts; do not repeatedly
rewrite status into the shared queue. Queue changes are for verified inventory
corrections or newly discovered input records only.

Receipts must distinguish these stages and retain the corresponding evidence:

| Stage | What a successful result means |
| --- | --- |
| Source review | Package structure, manifests, metadata, source locks, dependencies, licenses, build recipes, and check code were inspected, with changes and unresolved gaps recorded. |
| Build or installation | The applicable build or installation actually ran in the recorded environment and produced the expected usable result. Existing binaries or historical logs alone do not establish a new successful build. |
| Functional validation | The installed result performed the intended operation using a meaningful check. File presence and version output alone are insufficient. Apply only the repository's explicitly authorized APT-wrapper exemption. |
| Release publication | The intended package was uploaded as an immutable Release asset, and the uploaded asset's complete byte count and SHA-256 were verified. Only verified publication receipts can contribute entries to the root package manifest. |

Record failed, blocked, interrupted, missing, and unobserved stages explicitly,
including a concrete reason and the available evidence. A later stage does not
silently prove an earlier one: an uploaded historical binary does not demonstrate
that its source builds, and a successful build does not demonstrate functional
correctness. Keep official benchmark and hardware qualification separate when
they apply.

Retain unpacked package definitions, recipes, tests, documentation, and provenance
in Git. Finished packages belong in Releases. Preserve original identifiers and
historical records; the number of archives or migrated worker groups is a
migration-progress measure, not additional resource coverage.

## Publish a qualified text-material worker package

A reviewed text-material artifact keeps its complete frozen manifest, authored
recipe and ordinary UTF-8 payload files under its content-addressed package
template. CPG creates the package and runs its installation and functional checks.
The worker transport only replays that frozen archive format, and refuses any
result whose complete SHA-256 or size differs from the CPG-tested artifact. It
does not create new package semantics, install software or qualify upstream tools.

Store explicit artifact checksums in `release-plans/workers/<tag>.json`. The
worker release tag must start with `worker-`. Rehearse the exact replay with:

```sh
python3 tools/publish_workers.py build <tag> --output /absolute/new/output
```

After the group has been reviewed, committed and pushed to `main`, an explicit
push of that commit to `publish-workers/<tag>` requests its Release. The worker
workflow uses the same `cpg-workloads-publication` concurrency group as the
pre-worker publisher; queued requests are retained rather than canceled.

The publisher rejects changed source inputs, incomplete functional evidence,
conflicting identities, a reused tag at another commit, unexpected remote assets
and any digest or byte-size mismatch. It uploads a draft first, verifies the
complete asset set, then publishes and records a verified receipt. The receipt
commit regenerates package rows from all compatible publication receipts while
preserving unrelated root-manifest fields. A failed non-fast-forward push is
retried from the new `main` without force-pushing.
