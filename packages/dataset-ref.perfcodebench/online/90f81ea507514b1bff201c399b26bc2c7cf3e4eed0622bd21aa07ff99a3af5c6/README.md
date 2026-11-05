# Exact online material recipe

Install the compiler-playground Python library, extract this small recipe to a
new directory, then run:

    python run.py prepare --cache /path/to/raw-cache --output /path/to/new-output

The recipe downloads the original public HTTPS input, verifies exact size and
SHA-256, reuses only verified raw bytes, and reproduces the existing complete
offline material package. Its artifact SHA-256 must match `online.json`.
`fetch` verifies only the complete input; `probe` reads a bounded HTTP prefix
and never admits it as a full input or an offline artifact. `--no-network`
requires an existing valid raw cache object. Output/cache directories must be
outside this immutable recipe directory. For source checkout use, add
`--framework-path /path/to/compiler-playground`.

The original catalog, source locks, license classification, notices and artifact
provenance remain unchanged. Public retrieval does not grant new license
clearance. This recipe does not compile, install, execute benchmarks, validate
Dataset interfaces, start an OCI runtime or add functional qualification.

Use the generated `.material.cpgpkg.tar.gz` through the existing CPG package
manager. A recipe bundle is not a CPG package or a renamed installation method.
