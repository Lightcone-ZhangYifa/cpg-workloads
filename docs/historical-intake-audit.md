# Historical input reconciliation, 2026-11-08

This is an audit of existing historical inputs. Package discovery, source-byte
integrity, historical execution evidence, current functional validation and
publication are separate. Nothing in this audit installs a package, qualifies a
benchmark or adds a Release asset. The original historical files remain the
restoration source; the local cold mirror contains independently verified bytes
under their SHA-256 identities.

## Input routing

The full SHA-256 inventory covers 918 files, including 791 files in the archive
collection. A generated per-file disposition records all 918 inputs:

| Disposition | Files |
| --- | ---: |
| Historical metadata and evidence retained | 257 |
| ZIPs with mixed members still requiring review | 485 |
| Standalone files with individual intake outcomes | 53 |
| Parts of readable split ZIP families, with other members pending | 88 |
| Standalone gzip TAR streams read through the gzip footer | 10 |
| Parts in gzip TAR split families read through the gzip footer | 18 |
| Parts of an ELF split stream with terminal completeness pending | 3 |
| Parts of the partially recovered worker-083 ZIP | 3 |
| Historical Git bundle retained | 1 |

The inventory contains four duplicate-SHA groups comprising 92 files. The
remaining 485 mixed ZIPs and 88 split-ZIP parts are **not** asserted complete:
individual member outcomes and manifest path declarations are recorded, while
other members, nested structures and evidence still require review. TAR stream
readability does not establish the validity of toolchains inside them.

## Package and source-byte intake

The generated intake receipt records 6,156 distinct archive/member jobs,
including 880 initially named package or evidence leads, 53 standalone or
known-identity file leads, content-named object leads, and four packages found
during unknown-object inspection. Outcomes include:

| Recorded outcome | Jobs |
| --- | ---: |
| New artifact records | 424 |
| Existing artifact identity with verified additional origin | 2,454 |
| Existing online recipe identity with verified additional origin | 163 |
| Locked raw source bytes verified and retained | 1,773 |
| Duplicate members independently streamed and SHA-256/size verified | 1,263 |
| Authored binary, large file, payload or source-projection holds | 46 |
| Original worker-labeled identities held outside the public source tree | 11 |
| Known historical acquisition-plan appearances left deferred | 4 |
| Historical preparation metadata retained in the original archive | 10 |
| Named truncated negative fixtures pending evidence review | 7 |
| Failed package metadata re-pack | 1 |

The 424 new artifact records include 379 held by static review and 45
statically eligible records. Static eligibility is a review outcome, not a
publication, installation, functional check or hardware observation. The
failed re-pack is an `apt.bear` wrapper whose reproduced bytes did not match
its original SHA-256; it remains a failure. Other APT wrapper re-packs were
metadata-only and did not call APT, install underlying packages or run their
functional checks.

The incomplete worker-083 stream has no readable complete ZIP central
directory. Sixteen complete members were recovered from its available prefix,
matched against the original 18-entry artifact index, and independently passed
the framework package verifier. All 16 were recorded as separate original
artifacts: six are held and ten are statically eligible. Provenance explicitly
identifies the available prefix, its part hashes and each recovered member;
it does not describe the prefix hash as a complete ZIP hash. The `ytopt` source
and binary artifacts remain unrecovered. No missing part was downloaded.

## Hash-named historical objects

ZIP central directories contain 37,499 hash-named object occurrences. The
existing catalog and exact source locks identify 5,219 occurrences for member
intake. Of the other 32,280 occurrences, a join to the original cumulative
workspace manifest and original embedded candidate manifests found:

| Declaration-level binding | Occurrences |
| --- | ---: |
| Cumulative manifest declares the same volume, member name and size | 32,192 |
| Embedded candidate manifest declares a new entry with the same hash name and size | 34 |
| SHA-name and size match a declared logical path, with no same-volume binding | 6 |
| Unmapped by those manifests | 48 |

These are *declarations and central-directory names*. They are not claims
that all 32,280 member payloads were read or independently hashed. The path
ledger retains partition, logical path, original volume and a path-based
category. For source-looking paths, exact directory-segment matches to retained
Dataset card IDs are marked as candidates; they neither create samples nor
qualify a Dataset. Multiple paths can refer to the same bytes and are not a
count of distinct samples. The original 1,862-resource, 195-Dataset,
76-Model and 18-Benchmark discovery denominators are unchanged.

All 82 occurrences that lacked a cumulative-manifest binding were subsequently
stream-hashed and inspected by header. Thirty-four also have embedded candidate
manifest declarations. Four valid previously uncataloged packages, the source
and binary pairs for `dataset-ref.epcc-openmp` and `dataset-ref.stream`, passed
the framework package verifier and were added as held artifacts. One further
CPG candidate was rejected by the current schema (`check.argv must be a list`)
after its bytes were verified. Remaining cases are retained and classified by
observed header; an unidentified header or a compressed-stream header does not
identify the complete payload or establish its owner.

## Reproduction and review boundaries

`tools/history_ledger.py`, `history_manifest_ledger.py`,
`history_object_lineage.py`, `history_unknown_objects.py`, `history_intake.py`,
`history_nonzip.py`, `history_other_files.py`, `history_prefix_intake.py` and
`history_disposition.py` operate on explicitly selected roots and emit local
receipts. Their generated receipts are review evidence, not a second package
catalog or an installable repository manifest. Original definitions,
source locks, license notices and historical qualifications remain attached to
their original identities. No historical worker assignment is used as a new
public software identity.

Authored templates and package manifests preserve original byte identities.
Some retained third-party notices, licenses and samples contain trailing
whitespace or final blank lines; changing those bytes would invalidate their
original inventory hashes. Consequently `git diff --check` reports those
preserved upstream whitespace exceptions. Code and test changes should still
pass their own whitespace checks. Large source archives, binary outputs,
package payloads and extracted source projections are held outside Git.
