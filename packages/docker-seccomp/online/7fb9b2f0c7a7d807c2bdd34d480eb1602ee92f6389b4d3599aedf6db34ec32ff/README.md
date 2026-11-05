# docker-seccomp: immutable original single-file online recipe

Run with the installed **original CompilerPlayground 0.21.x API**:

    python run.py prepare --recipe . --cache /path/to/download-cache --output /new/output

`--no-network` requires the **complete exact 17,867-byte original JSON** already cached under its SHA-256; source is the original pinned HTTPS URL, not current branch HEAD. This recipe downloads (when network permits), verifies the full source SHA and byte length, copies the original single JSON (extract=false) to `policy/docker-default-seccomp.json`, and runs the production pack and verify APIs. Output is accepted only when its SHA, size, full manifest and inventory exactly match the paired Ubuntu 24.04 offline material artifact.

`fetch` only admits complete locked raw source data. `probe` only checks a bounded HTTPS prefix and cannot qualify the material artifact. Material check and a separate Debian 13 host-variant installation do not qualify original Ubuntu24 installation, native binary code, daemon OCI execution, Dataset or official Benchmark. Original source URL, commit, license and catalog are preserved; packaging is not new upstream licensing.
