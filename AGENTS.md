# CPG Workloads contributor instructions

- This repository is a software source. Keep only unpacked package definitions,
  recipes, tests, documentation, and provenance in Git; publish finished packages
  as immutable GitHub Release assets.
- Preserve `compiler-playground` as the only framework/package-manager implementation.
  Do not copy the framework here or create a second installer/dependency solver.
- Package discovery is not acquisition, installation, build, functional validation,
  official benchmark qualification, or hardware qualification.
- APT wrappers have the explicitly requested functional-test exemption. The
  authorized trusted-delivery path uses static identity, source-lock and license
  review and records unexecuted build/install and functional checks as `not_run`.
  Retain actual historical evidence under its original identity; do not transfer
  qualification to a new package identity or label static checks as functional.
- Prefer quick static inspection of trusted deliveries. Do not run new installs,
  functional checks, regression suites or rebuild verification unless requested.
- Preserve original package IDs, source locks, dependencies, licenses, recipes,
  check code, and original historical records. Keep the historical denominator 1,862.
- Contributions use disjoint software package directories and catalog receipt
  files. Regenerate the root manifest from verified release receipts; preserve
  every unrelated software entry. Inspect current main before any ref update; never force-push.
- Organize package IDs, source masters, recipes, catalogs, releases and asset names
  by the software or reference resource itself. Publish each supported package type
  as its own downloadable artifact. Delivery batches and contributor assignments
  are internal bookkeeping and must not appear in the published source tree or releases.
- Do not execute another session's unfinished jobs.
- Use a dedicated scratch directory and process one outer archive/one inner package
  at a time. Never delete another session's files or a unique unpublished result.
- Preserve missing, failed, blocked, interrupted, and unobserved states. Do not add
  a release URL to the root manifest until the upload's full SHA-256 and size are verified.
- Do not modify automation schedules as part of repository maintenance.
- Treat `publish/<tag>` as an explicit publication request. Existing release tags,
  plans, and assets are immutable. Same package identity with different bytes needs
  a new build identity and a separately reviewed record.
