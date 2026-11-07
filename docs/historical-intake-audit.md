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
| ZIPs retained with unresolved mixed members | 485 |
| Standalone files with individual intake outcomes | 53 |
| Parts of readable split ZIP families retained with unresolved members | 88 |
| Standalone gzip TAR streams read through the gzip footer | 10 |
| Parts in gzip TAR split families read through the gzip footer | 18 |
| Parts of an ELF split stream with terminal completeness pending | 3 |
| Parts of the partially recovered worker-083 ZIP | 3 |
| Historical Git bundle retained | 1 |

The inventory contains four duplicate-SHA groups comprising 92 files. The
485 mixed ZIPs and 88 split-ZIP parts have an archival-retention disposition.
Their workload leads have separate outcomes, and the path ledger identifies
historical evidence, framework files, Git state, resource integrations and
candidate Dataset source units. Other members and nested structures remain
explicitly unresolved; the archives are **not** asserted completely verified.
TAR stream readability does not establish the validity of toolchains inside them.

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

The full change adds **447** artifact records: the first seven, the 424 in the
table, and 16 recovered prefix members below. Of these, **392 are held** and
**55 are statically eligible**. The four EPCC OpenMP and STREAM records below
are included in the 424, not additional records. Static eligibility is a review outcome, not a
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
category. The path ledger flags 14,207 source-looking logical paths with exact
directory-segment matches to retained Dataset card IDs, including paths for
`tacle-bench`, `codecontests-plus`, `blis` and `polybench-c`. These are
candidates; they neither create samples nor
qualify a Dataset. Multiple paths can refer to the same bytes and are not a
count of distinct samples. The original 1,862-resource, 195-Dataset,
76-Model and 18-Benchmark discovery denominators are unchanged.

All 82 occurrences that lacked a cumulative-manifest binding were subsequently
stream-hashed and inspected by header. Thirty-four also have embedded candidate
manifest declarations. Four valid previously uncataloged packages, the source
and binary pairs for `dataset-ref.epcc-openmp` and `dataset-ref.stream`, passed
the framework package verifier and were added as held artifacts. One further
CPG candidate was rejected by the current schema (`check.argv must be a list`)
after its bytes were verified. Among the 48 still lacking a manifest path
binding, those four packages and the one rejected candidate account for five;
the other 43 have 19 gzip-TAR headers, 19 unidentified binary headers, three
XZ headers, one ZIP header and one text header. These cases remain retained
with their source volume, member name and verified byte identity in the case
table. A header does not identify the complete payload or establish its owner.

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

## Recorded receipt identities

The following generated receipts are retained outside Git. Hashes identify the
specific observations used above; they do not authenticate an upstream publisher.
The recovered-prefix `receipt.json` and `artifact-index-comparison.json` reside
beside the recovered bytes in the cold recovery directory.

| Receipt filename | SHA-256 |
| --- | --- |
| `history-inventory-20261108.json` | `ada34125ffc6ca4c60068b56e406a04934f322b06306103bff589d40fa3b29b6` |
| `history-member-ledger-expanded-v3-20261108.json` | `609d5f9a574c4bc8de3197b453b81ddf642e984ac7750c075a68549622c17468` |
| `history-member-ledger-expanded-v4-20261108.json` | `819de62f23d16a452a68fd8cdbc9540c5f6e0da1c0df189442e03fad6ae8be2d` |
| `history-member-ledger-expanded-v5-20261108.json` | `8cb91379df5b9befd46b15e39dc0f63c4068dfccdcf5d629a7b53c6a6961472d` |
| `history-intake-state-20261108.json` | `ae42eeff53f2b0455253bf85efa22509f6d055cace0cbc2e893d482f2143f8a2` |
| `history-manifest-ledger-expanded-v4-20261108.json` | `aae355bdc5a840d2edb2c110b17c60c1a46f3921bba532d6258b96a977dd4cb4` |
| `history-object-lineage-v2-20261108.json` | `c346f336657ca67b248da81799429f7623c13f42007b55739c8ff717564ed283` |
| `history-object-lineage-v4-20261108.json` | `1996edc66d8258e97811158d5f384acae56a43530e2e12d084fcd594ba3bf5af` |
| `history-unknown-object-cases-20261108.json` | `92223d00ae15473fe74d61bf15f05a8428d8fb547fa2a4009323b45a9b455fdb` |
| `history-nonzip-streams-20261108.json` | `827badf9279d79a9fffe61bc5d09ea1622b606f5e84bc95013b5b3fe1cec8388` |
| `history-other-files-20261108.json` | `837ea915ecc9141a8cc56a43dad590c3a24a407b252c748a0b24deb85f0e6248` |
| `history-prefix-intake-083-20261108.json` | `6238f0aa2ca2db4b3c3505bd23af70dd3c21db8cec715029df2f71048410e080` |
| `history-disposition-working-20261108.json` | `235676b08256d4aeb901d292eac9cfa1fdb1a83fb9ae46067f097a6b55f75fed` |
| `history-disposition-final-v4-20261108.json` | `be0265ed8314585261d5a98275fd17f78f4bed27ae9305ce143e9aae70f0fd31` |
| Recovered-prefix `receipt.json` | `393f3a4eeaa9d49ad1e502f71a2ec51389175fd4d68e9a802f19da6ea8c56361` |
| Recovered-prefix `artifact-index-comparison.json` | `037e0da1e44d830ffad06784f7248ee884051000f50c4344bc99943556d2ab02` |

## Replay commands

Run these from a workloads checkout after explicitly setting `HISTORY`,
`FRAMEWORK`, `WORKLOADS`, `RECEIPTS`, `OUT`, `COLD`, `SCRATCH`, `RECOVERY` and
`WORKSPACE_MANIFEST` to the desired paths. `OUT` and `SCRATCH` must be new
locations outside `HISTORY`. The two intake commands write artifact templates
and records to `WORKLOADS` and verified bytes to `COLD`; use a fresh isolated
checkout and cold directory for a replay. The other commands read input bytes
and write receipts. The original cumulative workspace manifest is required to
have SHA-256 `27d074e7539b56552ad69e138d966e72c659b72d75c8e6330b12d8fffbce8ce5`.

The recorded receipts describe an earlier catalog state and earlier versions of
the intake code. A new replay against a later catalog can classify an artifact
as already known and need not reproduce the old receipt hash. Preserve the
recorded receipts when exact historical outcomes are needed.

```sh
python3 "$FRAMEWORK/tools/history-inventory.py" --history-root "$HISTORY" \
  --output "$OUT/inventory.json" --hash --zip-index
python3 tools/history_ledger.py --inventory "$RECEIPTS/history-inventory-20261108.json" \
  --history-root "$HISTORY" --framework-root "$FRAMEWORK" --workloads-root "$WORKLOADS" \
  --output "$OUT/member-ledger.json"
python3 tools/history_manifest_ledger.py --ledger "$RECEIPTS/history-member-ledger-expanded-v4-20261108.json" \
  --history-root "$HISTORY" --framework-root "$FRAMEWORK" --workloads-root "$WORKLOADS" \
  --output "$OUT/manifests.json"
python3 tools/history_object_lineage.py --ledger "$RECEIPTS/history-member-ledger-expanded-v5-20261108.json" \
  --manifest "$WORKSPACE_MANIFEST" \
  --expected-manifest-sha256 27d074e7539b56552ad69e138d966e72c659b72d75c8e6330b12d8fffbce8ce5 \
  --history-root "$HISTORY" --framework-root "$FRAMEWORK" --output "$OUT/lineage.json"
python3 tools/history_unknown_objects.py --lineage "$RECEIPTS/history-object-lineage-v2-20261108.json" \
  --ledger "$RECEIPTS/history-member-ledger-expanded-v5-20261108.json" --history-root "$HISTORY" \
  --framework-root "$FRAMEWORK" --scratch "$SCRATCH/unknown" --output "$OUT/object-cases.json"
python3 tools/history_intake.py --ledger "$RECEIPTS/history-member-ledger-expanded-v5-20261108.json" \
  --case-table "$RECEIPTS/history-unknown-object-cases-20261108.json" --history-root "$HISTORY" \
  --framework-root "$FRAMEWORK" --workloads-root "$WORKLOADS" --cold-root "$COLD" \
  --scratch "$SCRATCH/intake" --state "$OUT/intake-state.json"
python3 tools/history_intake.py --ledger "$RECEIPTS/history-member-ledger-expanded-v5-20261108.json" \
  --history-root "$HISTORY" --framework-root "$FRAMEWORK" --workloads-root "$WORKLOADS" \
  --cold-root "$COLD" --scratch "$SCRATCH/intake" --state "$OUT/intake-state.json" --retry cold-alias
python3 tools/history_nonzip.py --ledger "$RECEIPTS/history-member-ledger-expanded-v3-20261108.json" \
  --disposition "$RECEIPTS/history-disposition-working-20261108.json" --history-root "$HISTORY" \
  --framework-root "$FRAMEWORK" --output "$OUT/nonzip-streams.json"
python3 tools/history_other_files.py --disposition "$RECEIPTS/history-disposition-working-20261108.json" \
  --history-root "$HISTORY" --output "$OUT/other-files.json"
python3 tools/history_prefix_intake.py --recovery "$RECOVERY" --history-root "$HISTORY" \
  --framework-root "$FRAMEWORK" --workloads-root "$WORKLOADS" --cold-root "$COLD" \
  --scratch "$SCRATCH/prefix" --output "$OUT/prefix-intake.json"
python3 tools/history_disposition.py --ledger "$RECEIPTS/history-member-ledger-expanded-v5-20261108.json" \
  --state "$RECEIPTS/history-intake-state-20261108.json" \
  --nonzip-state "$RECEIPTS/history-nonzip-streams-20261108.json" \
  --other-state "$RECEIPTS/history-other-files-20261108.json" \
  --prefix-state "$RECEIPTS/history-prefix-intake-083-20261108.json" \
  --lineage-state "$RECEIPTS/history-object-lineage-v4-20261108.json" \
  --unknown-cases "$RECEIPTS/history-unknown-object-cases-20261108.json" \
  --output "$OUT/disposition.json"
```
