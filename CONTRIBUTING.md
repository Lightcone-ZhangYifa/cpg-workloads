# Contributing

Keep package changes focused on their definition, authored recipe and functional
test. Preserve all exact upstream input identities and license notices. Explain
which target was actually tested and retain failures separately from passing checks.

Use an isolated directory for source, build, and installation. Only verified
immutable raw inputs may be cached across builds; do not share writable prefixes.

Run the repository validator and publication regressions. Resource-specific tests
also require the documented Compiler Playground checkout and actual prerequisites.
A skipped resource test is not a successful build or functional qualification.

Finished packages are published by explicit Release plans. APT wrapper exemptions
must not extend to Python wrappers or any native/static resource. Changes to the
same version/build/method/target may not replace already published bytes.

For parallel contributions, add disjoint catalog receipts and package paths,
refresh `main`, and regenerate the root manifest. Preserve work already submitted
by other contributors. Do not force-push or rebuild historical qualification counts.

## Static migration of previously delivered artifacts

For an explicitly requested static migration, set `review_policy: static-trust-v1` and retain the original execution evidence. Inspect identities, package structure, licenses, source locks, and declared checks without running a build or workload. A software artifact other than an APT wrapper must declare a meaningful functional check; a material artifact may declare an integrity/read check. Record unexecuted checks honestly. Publish original bytes after full SHA-256 and size verification; keep masters in Git and products in Releases.
