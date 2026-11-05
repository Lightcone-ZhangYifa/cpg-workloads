# xxHash v0.8.4 resource qualification

This integration extends the existing `xxhash` ID. The original source lock and
entire `metadata.catalog` object are preserved. There are two explicit package
definitions, selected through the existing `pack --definition` interface:

| Definition | Installation method | Contents |
|---|---|---|
| `material-profile.json` | `material` | Complete original source, CLI, tests, references and license files; no compilation |
| `package.json` | `source` | Original locked archive, a build recipe, official tests, installation and functional checks |
| `package.json` | `binary` | An independently copied and checked installed CLI, static/shared library, C headers, usage, oracle and API probe |

The material definition is the exact original file, not a reduced resource. A
material install verifies the archive and every copied file. Executable checks
remain **not_run**, because that definition does not declare any executable.
The old selector catalog keeps its historical material behavior.

## Supported native build profile

The profile targets Linux x86_64, Ubuntu 24.04. It declares the existing exact
`apt.build-essential=12.10ubuntu1` build prerequisite and
`apt.python3=3.12.3-0ubuntu2.1` check interpreter prerequisite. The recipe uses
`/usr/bin/cc`, `/usr/bin/make` and `/usr/bin/python3`; it does not install or
upgrade system packages. APT still owns the actual transitive system closure.
Qualification records the compiler, Make, Python and libc observations and
their executable hashes. It does not claim those observations are an OCI image
or a reproducible operating-system dependency snapshot.

Upstream Make builds static/shared libraries and the CLI with `-O2 -g0`, library
dispatch and CLI dispatch enabled, without `-march=native`. The recipe first
runs upstream `make check` and `make test-xxhsum-c`. It then installs the
documented CLI links, headers, libraries, man pages and pkg-config metadata.
Only the installed pkg-config prefix is made relative to `pcfiledir`.

The C API probe is compiled against the installed headers and shared library.
It uses upstream's unmodified `tests/sanity_test_vectors.h` as the independent
fixed oracle and additionally checks streaming across length/alignment strata.
Its `$ORIGIN/../lib` RUNPATH supports independent relocated prefixes. The Python
checker confirms the actual loaded library belongs to the selected prefix,
checks all four CLI checksum families and requires corrupted input to fail.
These are bounded correctness checks, not performance measurements or complete
upstream release qualification.

## Replay and package maintenance

From the outer workspace, with the Python package source available:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 resource-integrations/v0180/worker-a/acquire.py xxhash
PYTHONDONTWRITEBYTECODE=1 python3 resource-integrations/v0180/worker-a/replay.py xxhash \
  --output resource-integrations/v0180/worker-a/evidence/xxhash/my-fresh-run --jobs 2
```

The output directory must not exist. The replay verifies the download lock,
material pack/install/inventory, source build and upstream tests, then packs a
binary and installs it into two fresh prefixes. It compares every file's bytes,
mode and symlink target, checks inode independence, and confirms modifying one
copy cannot alter the other two. A known mutation must fail inventory checking
and is restored before completion. All installation receipts, English reports,
checks, build commands and logs are retained in the run directory.

The `usage.examples` fields in `package.json` provide direct `cpg packages pack`
commands for all three artifact forms. Source packages embed the exact original
archive. Material packages require the verified unpacked tree. Binary packages
require a successful source installation and explicit `--relocatable`; publish
only after the independent-prefix qualification passes. Publish its source
artifact alongside the binary to preserve source/material access and license
compliance. The query interface exposes both definition paths and states which
locations require a source or material install.

## Primary implementation references

- [Exact upstream source tree](https://github.com/Cyan4973/xxHash/tree/c87183a77d67f7d37e3d2d1b7eaac5e7c695e4f0)
- [Maintained build, install and test targets](https://github.com/Cyan4973/xxHash/blob/c87183a77d67f7d37e3d2d1b7eaac5e7c695e4f0/Makefile)
- [Original fixed test oracle](https://github.com/Cyan4973/xxHash/blob/c87183a77d67f7d37e3d2d1b7eaac5e7c695e4f0/tests/sanity_test_vectors.h)

The qualification uses those files from the exact SHA-256-verified source
archive, rather than relying on a moving branch or a host-installed xxHash.
