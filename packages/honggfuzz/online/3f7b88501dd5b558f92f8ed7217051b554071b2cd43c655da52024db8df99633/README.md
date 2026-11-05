# Exact archive-container online material recipe

With compiler-playground installed, run:

    python run.py prepare --cache /path/to/raw-cache --output /path/to/new-output

The original fixed HTTPS source archive is downloaded and checked in full. The
material view stores that exact archive and a deterministic full member index.
Upstream link targets remain inside the original archive; this recipe never
extracts them. Original sources/extract/strip_root/catalog/license fields remain
unchanged, while the explicit material representation is archive-container.

The output must reproduce the already qualified offline package byte for byte.
`--no-network` accepts only an existing valid raw cache; `fetch` only acquires
the full input and `probe` only records a partial transport observation. This
recipe adds no native, Dataset, hardware, benchmark or OCI qualification.
