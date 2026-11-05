# Resource deployment report

Operation status: **installed**. Resources: **1**.
Generated (UTC): `2026-11-01T10:47:57.639162+00:00`.

A deployment snapshot of acquisition, integrity, installation and declared checks; not full-feature, physical-target or benchmark qualification.

`not_run` means no execution evidence was supplied. `blocked` records an unmet prerequisite or an explicit hardware-probe result. Installation, version output and availability probes (files, help, configuration, lists or syntax) do not imply a functional check passed.

## Summary

| Resource state | Count |
| --- | ---: |
| installed_unchecked | 1 |

## Environment

```json
{"arch": "x86_64", "distribution": "ubuntu", "distribution_version": "24.04", "os": "linux"}
```

## Every requested resource

| ID | Version / build | Prefix | Acquisition | Acquisition origin | Integrity | Installation | Installation source | Version checks | Availability checks | Functional | Hardware | State |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reference-pack.worker-011 | 2026.11.01.1 / worker-011-v001 | /workspace/scratch/7f487a211dd5/integration-validation/worker-011/a/prefixes/reference-pack.worker-011 | acquired | local_resource_package | verified | installed | {"method": "material", "origin": []} | not_run | passed | not_run | not_run | installed_unchecked |

## Locate resources and evidence

Use `cpg packages list --installed`, `cpg packages search QUERY`, `cpg packages info ID`, `cpg packages paths ID`, and `cpg packages check ID` for current package state and usage. These queries are the authoritative agent interface. This report records the deployment snapshot; `report.json` retains individual stage evidence and check logs.
