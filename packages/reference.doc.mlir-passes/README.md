# MLIR Pass Contracts

Resource `reference.doc.mlir-passes`, version `20.1.8`, build `1`, artifact type **material**.

MLIR 20.1.8: all 30 generated-document includes from Passes.md are resolved; the selected TableGen include closure is complete. The delivered text is upstream source plus a lexical definition index, not llvm-tblgen output or the current website.

This standalone package contains this resource's selected upstream source closure, applicable licenses, a local reader and static indexes. The immutable upstream commit is `87f0227cb60147a26a1eeb4fb06e3b505e9c7261`. SHA-256 and Git blob identities are recorded in `source-lock.json`.

The 30 generated pass-document includes are mapped to their fixed CMake/TableGen source in `reference.json` and the installed resource descriptor. No generated website or runtime registration is claimed.

## Use

Install its `.cpgpkg.tar.gz` with the existing CPG PackageManager. Use `python3 -B <prefix>/reference_reader.py list`, `search`, `read`, `symbols`, `passes`, or `index` to inspect the retained material. A foreign entity ID or a path outside this source closure is rejected.

## Rebuild from the repository

With the official `compiler-playground` package available:

```sh
python3 -B tools/build_reference_material.py --package packages/reference.doc.mlir-passes --output /absolute/path/to/new/reference.doc.mlir-passes.material.cpgpkg.tar.gz
```

The builder uses local sources, generates deterministic indexes and calls the official CPG pack API. It requires the exact artifact lock and does not install the upstream software.

## Qualification

The newly split artifact receives static source, identity, license and manifest review. Its declared reader checks have not been executed under this new artifact identity. No compiler execution, official benchmark, trained model, dataset, OCI or hardware qualification is claimed.
