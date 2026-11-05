# SQLite 3.54.1 resource qualification

The existing `sqlite` resource now has a canonical-source build and an
independently deployable binary, while retaining the complete original material
view. No resource ID, original source lock or catalog fact was replaced.

| Explicit definition/method | Contents and behavior |
|---|---|
| `material-profile.json`, `material` | The original definition, byte for byte; every original source, public test, corpus, extension and reference file is copied and inventoried |
| `package.json`, `source` | The original locked SQLite archive, deterministic recipe inputs, native compilation, actual upstream checks and installed checks |
| `package.json`, `binary` | CLI, static/shared library, C headers, generated amalgamation, usage, licenses, exact static zlib material and executable checks |

All three use the existing `cpg packages pack --definition` interface. Query
`cpg packages info sqlite` for the actual definition, commands and locations;
`cpg packages paths sqlite` exposes the selected copy. The material view has
no executable checks, so it reports **not_run** for those checks while still
requiring complete byte-inventory verification. The old selector's material
catalog remains unchanged.

## Native build and dependency identity

The target is Linux x86_64, Ubuntu 24.04. Source builds declare the existing
`apt.build-essential=12.10ubuntu1` and
`apt.zlib1g-dev=1:1.3.dfsg-3.1ubuntu2.2` identities. Checks declare
`apt.python3=3.12.3-0ubuntu2.1` and use `/usr/bin/python3`. No recipe performs
an APT installation, upgrade or removal.

SQLite is built from its canonical source with upstream's bundled Jim Tcl for
code generation. The original source is copied before building and is not
patched. The configuration enables the upstream `--all` SQL feature set,
thread safety and loadable extensions, and builds shared/static libraries.
Readline, editline, the separate full Tcl extension and absolute RPATH are
disabled explicitly. FTS5, RTREE, JSON, session tracking and pre-update hooks
are checked at runtime. The public source and scripts for all other variants
remain available in the original material view.

The pinned SQLite release auto-detects zlib. To retain ZIP/DEFLATE functionality
without silently accepting a different installed zlib version, this recipe
uses the exact existing Ubuntu development package's **static** `libz.a`,
`zlib.h` and `zconf.h`. SHA-256 and size are fixed for the `.deb` and for each
consumed file in `recipe/zlib-lock.json`; the copyright notice is copied too.
They are placed under `share/compiler-playground/sqlite/zlib` in each independent
installation. The unchanged upstream configure script receives explicit
`CPPFLAGS`/`LDFLAGS`, and Make receives an explicit `LDFLAGS.zlib` archive path.
The linker search directory contains only the verified static archive.
An actual `ldd` check rejects accidental linkage to host `libz.so`.

On a machine where that exact APT development package is installed, the normal
source recipe verifies its files under `/usr`. The maintainer replay can instead
privately extract the exact locked `.deb`, pass an explicit build-dependency
path binding, and use the same file checks. That path is recorded as private
payload qualification, **not** as an installed or validated APT transaction.
The source package does not pretend to contain all system dependencies.

## Actual qualification

The recipe runs upstream `make sourcetest`, then builds the public `fuzzcheck`
harness and executes the complete original `test/fuzzdata1.db` corpus with
PRNG seed 1 and an explicit 10-second per-case timeout. The recorded run
completed **9,917 tests with zero errors**. This is one public corpus, not
the full upstream release test matrix; `fuzzcheck` has its own upstream test
compile flags. The installed binary has separate checks.

Both the CLI and the linked C API must report version 3.54.1 and the exact
Fossil source identity
`555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76`.
The API probe's relative RUNPATH selects the installation's own library;
the checker confirms its resolved location and removes ambient loader overrides.
Checks execute prepared statements with binary data, foreign-key rejection,
transaction rollback, WAL reads during a write transaction, real conflicting
writer rejection, online backup, integrity checking, FTS5, RTREE, JSON and a
real session changeset. CLI tests cover persistent data, backup, dump/restore,
uniqueness failure and a compiled extension that is actually loaded and run.

ZIP testing crosses implementations in both directions: SQLite creates a
DEFLATE archive that Python's `zipfile` decodes byte for byte; Python creates
a DEFLATE archive that the selected SQLite CLI decodes byte for byte. Checking
the actual ZIP method prevents an uncompressed archive from passing this test.

Source installation and two separate binary installations passed these checks.
Every payload file, mode and symlink target matched; regular files had independent
inodes. Mutating one copy changed only that copy's inventory result. The binary
keeps source and notices for its bundled static zlib and exports SQLite's
generated `sqlite3.c`, `sqlite3.h` and `shell.c` amalgamation for research use.

## Repeat a maintained build

From the outer workspace:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 resource-integrations/v0180/worker-a/replay.py sqlite \
  --definitions resource-integrations/v0180/worker-a/packages \
  --cache resource-integrations/v0180/download-cache \
  --output resource-integrations/v0180/worker-a/evidence/sqlite/my-fresh-run --jobs 2
```

After adoption, the batch entry point passes the project's active
`compiler-playground/resources/packages` directory to `--definitions`.
The output directory must be new. The replay uses the existing shared download
cache and fetches only missing exact SQLite/zlib archives. It builds the raw,
source and binary artifacts, verifies each installation and records relative
artifact paths, SHA-256, byte counts and scope in `summary.json`. All package
recipes and their hashes come from that selected active definition directory.

The direct source/binary/material `cpg packages pack` forms are in
`package.json` under `usage.examples`. Binary packaging uses an already checked
installation and explicit `--relocatable`, followed by independent-prefix
verification on the same declared target. It does not imply compatibility
with a different OS, ABI or every CPU family.

## Additional upstream Tcl qualification on a user's build machine

The host used for this qualification did not have the exact full Tcl development
prerequisites. The Tcl suite is **not_run**, and proprietary TH3 is separately
distributed upstream and is not claimed. To run upstream's public Tcl developer
suite in a suitable Ubuntu 24.04 environment, first install the existing exact
wrapper definitions and their resolved APT closure:

```sh
cpg packages install apt.tcl
cpg packages install apt.tcl-dev
```

The existing pinned version for both wrappers is `8.6.14build1`; preserve that
identity and read the actual installation receipts. Then use a fresh build
directory and the complete original source tree:

```sh
mkdir sqlite-tcl-validation
cd sqlite-tcl-validation
/path/to/original-sqlite-source/configure \
  --with-tcl=/usr/lib/x86_64-linux-gnu \
  --with-tclsh=/usr/bin/tclsh8.6 --disable-readline --all
make -j2
make devtest
```

That is an executable follow-up workflow, **not an observed test result**.
It uses the user's actual environment and should receive its own receipt and
tool/dependency identity record. Preserve failures; do not substitute a CLI
smoke test for the upstream suite.

## Evidence retention and references

The successful native run is `evidence/sqlite/qualification-2/summary.json`.
The earlier exploratory no-zlib build is retained as a failed attempt: changing
an upstream build script caused SQLite to mark its source ID with `alt1`, which
the strict installed-version check correctly rejected. It is not an active
default profile or a published qualification. The successful recipe retains
ZIP support and leaves upstream source files unchanged.

Completed build/install trees may be removed under the user's explicit cleanup
policy. The original archives, CPG artifacts, recipes, complete inventories,
all commands/logs and `cleanup-receipt.json` are retained. Installation receipts
then describe historical qualification events, not live installed prefixes.
Regression tests restore temporary payloads from verified CPG artifacts.

- [Official canonical-source compilation](https://www.sqlite.org/howtocompile.html)
- [Official testing scope and separate test suites](https://www.sqlite.org/testing.html)
- [Exact canonical SQLite archive](https://www.sqlite.org/2026/sqlite-src-3540100.zip)
- [Exact upstream Fossil identity](https://www.sqlite.org/src/info/555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76)
- [Exact Ubuntu zlib development package](https://archive.ubuntu.com/ubuntu/pool/main/z/zlib/zlib1g-dev_1.3.dfsg-3.1ubuntu2.2_amd64.deb)
