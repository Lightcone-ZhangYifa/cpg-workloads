# Worker 011 source migration

This directory is the unpacked source master for `reference-pack.worker-011`.
It retains the original worker's local reference sources, preparation and index
builders, reader, tests, package definition, recipe, assignments, licenses, and
historical evidence. Finished `.cpgpkg.tar.gz` files are excluded from Git.

The current definition is `2026.11.01.1` / `worker-011-v002`. Its functional check exercises
the offline reader across the four reference assets and verifies the pinned
source identity. This qualifies the reader operations recorded in the migration
receipt; it does not qualify LLVM or MLIR execution, Dataset use, official
benchmarks, or hardware. The historical 1,862-resource denominator is unchanged.

## Source and artifact layouts

The queryable package master is `packages/reference-pack.worker-011/package.json`
with its adjacent `recipe/`. The frozen artifact template is
`packages/reference-pack.worker-011/artifacts/050720b9f7b9095d878996dc014f7ab68f411fe1f0be3e9695a19cad04c40b38/`; it contains the manifest,
matching package definition, recipe, and all 98 text payload files. These paths
are relative to the repository root. The installed artifact belongs in Releases.

The retained `payload/materials/` and `payload/evidence/upstream/` trees supply
the locked upstream inputs for offline rebuilding. `tools/build_payload.py`
recreates the local indexes, asset metadata, reader payload, and inventory from
those inputs. `tools/rebuild_material.py` then calls the existing CPG `pack` API
using the fixed `cpg/packaging-provenance.json`; it does not implement an installer
or an alternative package format.

## Offline rebuild

Use an environment with `compiler-playground` installed; this migration was
validated with CPG 1.0.0 and Python 3.11 or newer. From this source directory:

```bash
python3 -B tools/rebuild_material.py   --output /absolute/path/to/new/reference-pack.worker-011.material.cpgpkg.tar.gz
```

The output must not exist. The command regenerates the payload in a temporary
directory, creates the material archive, and checks its complete SHA-256, byte
count, and manifest identity against `cpg/package-index.json`. It uses local
source inputs only. A mismatch fails instead of silently rewriting the lock.

Current archive lock:

- Build: `worker-011-v002`
- Bytes: `287072`
- SHA-256: `050720b9f7b9095d878996dc014f7ab68f411fe1f0be3e9695a19cad04c40b38`
- Manifest SHA-256: `7dce33d0f14b035b4d5325193e6427d333ff4cb848387ee5ef99aca84ec4a443`

## Historical evidence

`DELIVERY-MANIFEST.json`, the original delivery notes, and old validation logs
describe the original ZIP delivery. They are preserved as historical evidence,
including the original absolute paths in those logs. They are not a new checksum
manifest for this modified Git checkout. The original v001 package metadata is
retained under `cpg/provenance/worker-011-v001/`; its availability-only evidence
has not been relabeled as functional validation. Earlier instructions naming CPG
0.21.14 document that original validation environment.

Current migration and validation status is recorded separately in
`catalog/workers/011.json` and its referenced evidence. The source queue does not
assert completion or publication; the Release receipt records publication and
remote byte verification.
