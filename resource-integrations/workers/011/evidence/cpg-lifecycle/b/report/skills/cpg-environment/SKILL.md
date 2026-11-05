---
name: cpg-environment
description: Discover and use compiler, dataset, benchmark, profiling, and hardware resources through the Compiler Playground package manager. Use before installing another tool or when locating an available resource, exact version, initialization, examples, or verification status.
---

# Use the prepared environment

1. Run `cpg packages list` for a compact category overview. Narrow it with `cpg packages list --installed --category CATEGORY`, or find candidates with `cpg packages search QUERY`.
2. Run `cpg packages info ID` for current usage, initialization, examples, provenance and verification state. Use `--version VERSION` when selecting among coexisting versions.
3. Run `cpg packages paths ID` for actual locations. Use the selected version's explicit paths and interpreter. Package-manager queries are the authoritative resource interface; do not infer availability from an old document or a package name.
4. Run `cpg packages check ID` when usability needs checking. Version, availability (files/help/configuration), functional and hardware checks establish different facts. Availability does not prove useful computation. Read `blocked` and `not_run` reasons, especially for hardware permissions and devices. Commands also accept `--json` for deterministic processing.
5. Consult `/opt/compiler-playground/reports/REPORT.md` for the English deployment snapshot and evidence paths when troubleshooting.

Keep source trees, datasets, inputs, answers and references available as selected by the developer. Recheck a tool after changing it or moving to a different host. Query one resource in detail instead of loading the complete inventory into context.
