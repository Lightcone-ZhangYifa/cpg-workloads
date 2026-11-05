# Zstandard v1.5.7 resource qualification

This extends the existing `zstd` resource ID with an explicitly configured native
Zstd installation. `material-profile.json` is the original definition, byte for
byte; its source lock and complete catalog record also remain unchanged in
`package.json`. The raw profile retains every upstream source file, input,
decoder regression frame, test, example and optional codec integration.

## Installation forms

| Definition and method | Behavior |
|---|---|
| `material-profile.json`, `material` | Copy and verify every original raw-source file; executable checks are `not_run` |
| `package.json`, `source` | Build upstream source in an independent copy, run official `make check`, install and run package checks |
| `package.json`, `binary` | Copy a previously checked installation to an independent same-target prefix, then rerun its checks |

These are explicit invocations of the existing `cpg packages pack --definition`
interface. They do not create extra resource IDs or change what the old
material selector exposes. Full packaging commands are part of the canonical
`usage.examples`, so `cpg packages info zstd` is the operational reference.

## Native profile and actual checks

The profile targets Ubuntu 24.04 x86_64 and declares exact existing wrappers
`apt.build-essential=12.10ubuntu1`, `apt.file=1:5.45-3build1`, and
`apt.python3=3.12.3-0ubuntu2.1`. The first two are build/test prerequisites;
Python is the installed checker interpreter. The replay observes existing
packages, compiler tools and libc. It does not install system packages or
claim that a full pinned APT closure or container image was deployed.

The maintained upstream Make build is used. `MOREFLAGS` supplies `-O2 -g0`
and a reproducible source-prefix mapping while preserving upstream's
target-specific PIC and visibility flags. No `-march=native` tuning is added.
CLI/shared-library multithreading, native dictionaries and upstream default
legacy decoders remain enabled. The static archive retains upstream's default
single-threaded configuration. The runtime C API probe selects the shared
library; it does not claim static-library-specific multithread qualification.

`HAVE_ZLIB=0 HAVE_LZMA=0 HAVE_LZ4=0` fixes the native Zstd profile and prevents
uncontrolled auto-linking to optional host codec libraries. Gzip/xz/lz4 CLI
compatibility is outside this binary profile. All original code needed to
build those variants remains available in the full source/material resource.

Source qualification runs upstream `make check` without modifying its test
script. Upstream intentionally excludes its long-data tests from that target.
The separate installed checks perform:

- Fifteen C API length/level combinations with frame-size validation, exact
  round trips, invalid-magic and truncated-frame rejection.
- Actual two-worker streaming and a raw-dictionary C API round trip.
- CLI levels 1, 3 and 9 with content checksums, decompression byte equality and
  deliberately truncated input.
- Dictionary training from deterministic records, dictionary compression and
  decompression, and required failure when the dictionary is absent.
- The four original valid upstream decoder regression frames and three
  original invalid frames, preserved byte for byte inside the binary.

The API probe uses `$ORIGIN/../lib`; the checker removes ambient
`LD_LIBRARY_PATH`/`LD_PRELOAD` and confirms the actual loaded library is under
the selected prefix. The pkg-config prefix is relative to `pcfiledir`.

## Maintainer replay

```sh
PYTHONDONTWRITEBYTECODE=1 python3 resource-integrations/v0180/worker-a/acquire.py zstd
PYTHONDONTWRITEBYTECODE=1 python3 resource-integrations/v0180/worker-a/replay.py zstd \
  --definitions resource-integrations/v0180/worker-a/packages \
  --cache resource-integrations/v0180/download-cache \
  --output resource-integrations/v0180/worker-a/evidence/zstd/my-fresh-run --jobs 2
```

After adoption, the batch tool passes the project's active
`resources/packages` directory to `--definitions`. The output directory must
be fresh. A successful summary contains relative paths, sizes and SHA-256
identities for `material`, `source` and `binary` artifacts. Every receipt,
English installation report, command, stdout/stderr log and original failure
remains available for inspection.

The replay installs the binary twice, verifies full inventories and independent
inodes, and proves that changing one copied file causes only that copy's
inventory to fail. This establishes independent same-target deployment; it
does not establish full fuzz coverage, sanitizers, every CPU/architecture,
OCI deployment or benchmark performance.

## Primary references

- [Exact source and maintained build instructions](https://github.com/facebook/zstd/blob/f8745da6ff1ad1e7bab384bd1f9d742439278e99/README.md)
- [Official test target definitions](https://github.com/facebook/zstd/blob/f8745da6ff1ad1e7bab384bd1f9d742439278e99/tests/Makefile)
- [CLI compilation configuration](https://github.com/facebook/zstd/blob/f8745da6ff1ad1e7bab384bd1f9d742439278e99/programs/README.md)
- [Library configuration and profile semantics](https://github.com/facebook/zstd/blob/f8745da6ff1ad1e7bab384bd1f9d742439278e99/lib/README.md)

The exact downloaded source files, rather than a moving branch or an ambient
host executable, are the basis for these build and test decisions.
