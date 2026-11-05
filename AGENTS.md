# CPG Workloads contributor instructions

- This repository is a software source. Keep only unpacked package definitions,
  recipes, tests, documentation, and provenance in Git; publish finished packages
  as immutable GitHub Release assets.
- Preserve `compiler-playground` as the only framework/package-manager implementation.
  Do not copy the framework here or create a second installer/dependency solver.
- Package discovery is not acquisition, installation, build, functional validation,
  official benchmark qualification, or hardware qualification.
- APT wrappers have the explicitly requested functional-test exemption. Every other
  release artifact requires actual build/install and functional evidence. Do not
  reclassify a file-presence or version-only probe as a functional test.
- Preserve original package IDs, source locks, dependencies, licenses, recipes,
  check code, and original historical records. Keep the historical denominator 1,862.
- New worker contributions use disjoint package directories and catalog receipt
  files. Regenerate the root manifest from verified release receipts; do not overwrite
  another worker's entries. Inspect current main before any ref update; never force-push.
- The current migration handles pre-worker deliveries only. Do not import numbered
  worker archives or execute another session's unfinished jobs.
- Use a dedicated scratch directory and process one outer archive/one inner package
  at a time. Never delete another session's files or a unique unpublished result.
- Preserve missing, failed, blocked, interrupted, and unobserved states. Do not add
  a release URL to the root manifest until the upload's full SHA-256 and size are verified.
- Do not modify automation schedules as part of repository maintenance.
- Treat `publish/<tag>` as an explicit publication request. Existing release tags,
  plans, and assets are immutable. Same package identity with different bytes needs
  a new build identity and a separately reviewed record.
