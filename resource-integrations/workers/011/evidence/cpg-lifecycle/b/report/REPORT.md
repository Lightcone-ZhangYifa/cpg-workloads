# Resource deployment report

Operation status: **reported**. Resources: **1**.
Generated (UTC): `2026-11-01T10:48:10.337623+00:00`.

A deployment snapshot of acquisition, integrity, installation and declared checks; not full-feature, physical-target or benchmark qualification.

`not_run` means no execution evidence was supplied. `blocked` records an unmet prerequisite or an explicit hardware-probe result. Installation, version output and availability probes (files, help, configuration, lists or syntax) do not imply a functional check passed.

## Summary

| Resource state | Count |
| --- | ---: |
| removed | 1 |

## Every requested resource

| ID | Version / build | Prefix | Acquisition | Acquisition origin | Integrity | Installation | Installation source | Version checks | Availability checks | Functional | Hardware | State |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reference-pack.worker-011 | 2026.11.01.1 / worker-011-v001 | /workspace/scratch/7f487a211dd5/integration-validation/worker-011/b/prefixes/reference-pack.worker-011 | acquired | local_resource_package | verified | removed | {"method": "material", "origin": []} | not_run | passed | not_run | not_run | removed |

## Locate resources and evidence

Use `cpg packages list --installed`, `cpg packages search QUERY`, `cpg packages info ID`, `cpg packages paths ID`, and `cpg packages check ID` for current package state and usage. These queries are the authoritative agent interface. This report records the deployment snapshot; `report.json` retains individual stage evidence and check logs.
