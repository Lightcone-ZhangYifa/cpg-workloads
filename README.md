# CPG Workloads

The software source for [Compiler Playground](https://github.com/Lightcone-ZhangYifa/compiler-playground).
Git stores unpacked package definitions, build recipes, functional checks, source locks, and audit records.
[Releases](https://github.com/Lightcone-ZhangYifa/cpg-workloads/releases) store the finished packages.

## Layout

| Path | Purpose |
| --- | --- |
| `manifest.json` | Machine-readable index of packages whose Release upload has been verified. |
| `packages/registry.json` | Discovery order and the historical catalog header. |
| `packages/<id>/package.json` | Current package definition; original IDs and exact upstream locks are retained. |
| `packages/<id>/recipe/` | Authored build and functional-check sources. |
| `packages/<id>/artifacts/<sha256>/` | Unpacked source template for one previously delivered package: manifest, definition, and recipe/tool sources. Installed payloads are excluded. |
| `packages/<id>/online/<sha256>/` | Unpacked historical online material recipe, including its preserved entry-point and acquisition contract. |
| `catalog/artifacts/` | Per-artifact structure, metadata, rebuild, and functional-check results. |
| `catalog/imports/` | One audit receipt per inspected delivery archive; failures and excluded members remain visible. |
| `catalog/releases/` | Verified canonical, dependency-variant, and online publication receipts used to generate the root manifest. |
| `catalog/historical-snapshots/` | Exact original artifact, manifest, and delivery-member bindings for historical alternatives. |
| `catalog/historical-releases/` | Verified historical publication receipts; these populate the separate root historical download index. |
| `catalog/revisions/` | Reviewed metadata and check-definition changes, with original and target manifest identities. |
| `catalog/reviews/license-holds.json` | Unreleased original artifacts whose redistribution terms remain unresolved, with any separately qualified public alternatives. |
| `release-plans/` | Explicit immutable lists of artifacts to publish together. |
| `resource-integrations/` | Historical maintainer drivers and evidence, retained with their original scope. |
| `tools/`, `tests/` | Repository validation and publication infrastructure, plus resource-specific tests. |

Each package retains its software identity, source locks, and provenance. The historical
discovery denominator remains **1,862 resources**; discovery, available input, successful
build, functional qualification, and publication are different measurements.

## Use package definitions

Install Compiler Playground, then select this checkout explicitly:

```bash
export CPG_WORKLOADS_ROOT=/absolute/path/to/cpg-workloads
cpg resources list
```

An existing `.cpgpkg.tar.gz` contains its own definition and can also be installed
without this checkout through CPG's existing package manager. For a remote software
source, pin the exact `manifest.json` byte size and SHA-256 from a trusted release.
Each package row keeps its local content-addressed mirror path and a separate HTTPS
Release download URL. Both the archive and every declared member are verified.

An `.cpgrecipe.tar.gz` contains an online preparation recipe. Read its included README
for the preserved entry point, acquisition locks, and offline artifact it prepares.
These recipes are indexed separately from CPG installation packages.

## Qualification rules

Every artifact records its qualification route. Execution-qualified artifacts retain
their original build and functional evidence. The explicit `static-trust-v1` migration
route checks structure, metadata, redistribution terms, source locks, and check
definitions without running a workload. It preserves earlier evidence and records
that no new build or functional run occurred.

1. Inspect each delivered package with the CPG archive verifier, including paths,
   inventory, hashes, modes, source locks, and dependency identities.
2. Preserve the complete original definition, recipe, test code, license metadata,
   source identity, and failure evidence in its source template.
3. Software packages other than APT wrappers need a meaningful functional-check
   definition. Material packages need a read or integrity-check definition. An
   execution-qualified result additionally requires the corresponding observed run;
   the static migration route only inspects these definitions.
4. APT wrappers are the sole functional-test exemption requested for this migration.
   Their payload-free packages are still validated and rebuilt to the exact original
   SHA-256. This does not claim an APT installation or execution.
5. Admit only artifacts that satisfy their recorded qualification route. Missing
   definitions, unresolved redistribution terms, interrupted historical builds,
   and unobserved execution or hardware remain explicit.
6. Verify the uploaded asset set, SHA-256, and sizes before adding its publication
   receipt to `manifest.json`. Never overwrite a published identity with different bytes.

Large input archives, upstream build trees, installed prefixes, `.cpgpkg`/`.cpgrecipe`
files, and compiler outputs do not belong in Git. Migration uses one outer archive
and one inner package at a time. Temporary data can be removed after its necessary
source template and audit record are preserved and its release status is known.

Unresolved redistribution holds are listed in
[`catalog/reviews/license-holds.json`](catalog/reviews/license-holds.json). Their
source templates remain available, but a held artifact is not a published package.
A listed alternative has its own exact identity and does not change the held
artifact's qualification.

A template's `authored-inputs.json` records external recipe inputs that remain in the
finished package but are omitted from Git. Each entry binds the original manifest
member to its HTTPS source, SHA-256, and byte size. Packaging restores only those
explicitly locked inputs; missing authored code is not treated as an external input.
Metadata revisions can preserve the exact original input bytes while changing only
the reviewed definition or check sources.

## Artifact naming

```text
cpg--<id>--<version>--<build>--<method>--<os>-<arch>--<sha256-prefix>.cpgpkg.tar.gz
```

Unsafe or long components are normalized with a suffix derived from the original
value. The full original version, build, target (including distribution), full hash,
byte count, and dependencies are in the manifest. Filenames are never used as a
substitute for package identity. Release batches contain at most 950 packages so
there is space for the manifest, checksums, and publication metadata.

## Maintainer commands

```bash
# Inspect one delivery; use a dedicated scratch directory outside this checkout.
python tools/import_archives.py /path/to/delivery.zip \
  --framework /path/to/compiler-playground --scratch /path/to/scratch \
  --static-trust

# Check repository invariants and the publication regression tests.
python tools/validate_repository.py
python -m unittest discover -s tests -p 'test_release_pipeline.py' -v

# Create explicit immutable publication plans from qualified artifacts.
python tools/release.py plan --prefix apt-wrappers-20261105 --batch-size 500
python tools/release.py build apt-wrappers-20261105-001 --output /path/to/new-output
```

Input scope is explicit: repeat `--exclude '<glob>'` to omit matching archive
names or nested member paths. Receipts record these omissions as `excluded_members`.

Publication is an explicit push to `publish/<plan-tag>` at the current `main`
commit. GitHub Actions rebuilds the exact audited archive bytes, publishes a draft
only after verifying every uploaded asset, then commits the publication receipt
and regenerated root manifest. It uses a narrowly scoped `GITHUB_TOKEN`, with no
personal access token. A new package installer or dependency solver is not introduced.

The repository's workflow files do not themselves enable remote branch protection
or change repository visibility. Record actual remote settings separately.

## License and provenance

Original CPG packaging code and documentation use the MIT license. Upstream software,
datasets, benchmarks, and documentation retain their own terms. A public download URL
or successful build does not grant redistribution permission. Each artifact preserves
its original license classification and any unresolved restrictions; restricted
materials must not be admitted to a public release merely because they were delivered
previously.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

### Static migration of historical deliveries

Artifacts marked `review_policy: static-trust-v1` were reviewed for structure, metadata, licensing, source locks and check definitions. Their existing execution evidence is retained; this migration does not claim a new build or test run. Each published file is verified against its original full SHA-256 and byte size. Large deliveries may be transferred directly to an ephemeral publishing runner using an encrypted, short-lived download specification; secrets and finished packages do not enter the source branch.

### Exact dependency profiles

Historical Python environments sometimes use different archives with the same software/version/build/method/target. Their original context and full hashes are retained in `catalog/dependency-profiles/`; build numbers and dependency pins are not rewritten. Published alternatives appear in the root `dependency_variants` list, separate from canonical software discovery.

For a package with frozen dependencies, select its ready manifest under `profiles/`. Each generated manifest contains one complete, unambiguous original context or package-specific dependency closure. The root `dependency_profiles` summary reports missing hashes until all required artifacts are public; an incomplete profile is never presented as installable. Online preparation recipes remain in `online_recipes` and are not CPG installation packages.

### Historical artifact snapshots

The root `historical_snapshots` list exposes verified public downloads for original
deliveries whose full software identity also occurs with different bytes. Each row
retains the original ID, version, build, target, manifest hash, and complete archive
hash. Select these artifacts by their full SHA-256. Their source descriptors bind
the exact original archive and member; published receipts live separately in
`catalog/historical-releases/`.

Historical snapshots do not participate in canonical identity resolution or in
generated ready dependency profiles. A preserved archive-member context does not
establish a complete dependency environment. Source descriptors become downloadable
index entries only after their actual Release assets and publication receipts have
been verified.
