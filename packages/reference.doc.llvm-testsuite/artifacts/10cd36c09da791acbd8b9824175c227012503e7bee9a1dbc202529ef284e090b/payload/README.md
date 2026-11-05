# LLVM test-suite

Resource `reference.doc.llvm-testsuite`, version `20.1.8`, build `1`, artifact type **material**.

Complete fixed-version test-suite Guide source document. No test-suite programs, External inputs or official benchmark execution are included.

This standalone package contains only this resource's selected upstream source closure, applicable licenses, a local reader and static indexes. The upstream commit is `87f0227cb60147a26a1eeb4fb06e3b505e9c7261`. Source SHA-256 and Git blob identities are recorded in `source-lock.json`.

## Use

Install its `.cpgpkg.tar.gz` with the existing CPG PackageManager. Then invoke `python3 -B <prefix>/reference_reader.py list`, `search`, `read`, or `index`. The reader rejects another entity ID and paths outside this source closure.

## Rebuild from the repository

With the official `compiler-playground` package available, run:

```sh
python3 -B tools/build_reference_material.py --package packages/reference.doc.llvm-testsuite --output /absolute/path/to/new/reference.doc.llvm-testsuite.material.cpgpkg.tar.gz
```

The builder uses local source inputs, generates deterministic indexes, and calls the official CPG pack API. It requires the existing exact artifact lock and does not install the upstream software.

## Qualification

The newly split artifact receives static source, identity, license and manifest review. Its declared reader checks have not been executed under this new artifact identity. No compiler execution, official benchmark, trained model, dataset, OCI or hardware qualification is claimed.
