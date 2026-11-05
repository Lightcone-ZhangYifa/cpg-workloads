# dataset-ref.dredd: exact complete static material recipe

This thin recipe reconstructs the independently qualified material package through the existing CompilerPlayground Python library. It embeds no upstream payload or model bytes. Install the CPG library or provide the recovered checkout using `--framework-path`.

```sh
python run.py validate
python run.py prepare --framework-path /path/compiler-playground --cache /path/raw-cache --output /path/new-material.cpgpkg.tar.gz
```

Preparation explicitly acquires every immutable source, recursive Gitlink and Git LFS input listed in `recipe/source-closure.json`; SHA-256 and byte lengths are mandatory. For offline recovery, add `--no-network --inputs-json /path/input-id-to-local-file.json`, or provide the exact files in the CPG content-addressed cache. The cache and fresh output must be outside this recipe directory.

All original resource identifiers, versions, source URLs and discovery fields, dependencies, targets, provider and catalog metadata are preserved. The LLVM-IR profile applies only its two explicitly reviewed absolute-link relocations; the common secure extractor is unchanged. Complete material and recipe inventories must match, and the reconstructed package must equal the qualified offline artifact byte-for-byte.

The resulting archive is installed, checked and removed through `PackageManager`. This is static material availability qualification. Native execution, semantic oracles, Dataset admission, official Benchmark scores, OCI and hardware qualification remain separate. All original license notices and catalog review labels remain in force.
