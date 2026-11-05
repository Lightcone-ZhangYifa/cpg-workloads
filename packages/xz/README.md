# XZ Utils 5.8.4 resource maintenance

The existing `xz` resource now has an explicit source/binary definition alongside
its original material definition. The source archive, complete `metadata.catalog`,
source/test/translation inputs and original selector identity are preserved.
`material-profile.json` is the byte-for-byte original definition and remains a
working `pack --definition --method material` entry.

## Discover and use

Start with `cpg packages info xz --json`, `cpg packages paths xz`, and
`cpg packages check xz --prefix <prefix>`. Select the desired installation prefix
explicitly if more than one source build is present.

The complete source build installs the upstream CLI tools and aliases into
`<prefix>/bin`, shared/static liblzma and development metadata into `<prefix>/lib`,
and public API headers into `<prefix>/include`. It also installs the upstream
shell tools (`xzgrep`, `xzdiff`, `xzless`, `xzmore`), English man pages, basic
documentation, licenses, examples and all compiled message catalogs. Raw source,
official test fixtures and translation inputs remain in the source installation's
receipt-selected `assets/corpora/xz` tree. Binary-only installs do not fabricate
that source tree.

```sh
export PATH="<prefix>/bin:$PATH"
<prefix>/bin/xz --threads=2 --check=sha256 -6 -c input.bin > input.xz
<prefix>/bin/xz -dc input.xz > restored.bin
<prefix>/bin/xz --robot --list -vv input.xz
LC_ALL=en_US.UTF-8 LANGUAGE=de <prefix>/bin/xz --help
```

Run `locale -a` first and use an installed non-C UTF-8 locale. Modern glibc
intentionally ignores `LANGUAGE` under `C.UTF-8`. If a minimal container has no
non-C locale data, initialize the desired locale in its base-image configuration
before NLS qualification; the separate `xz-nls` check outputs `initialization_required` and `nls:not_run`
with instructions when none is available. Its nonzero exit is recorded as a failed
NLS qualification by the current framework; independent `xz-functional` API and
decompression results remain distinct. It does not claim a broken compressor or
silently claim that translation worked. The frozen schema currently reserves
dynamic blocked return codes for hardware checks.

For C development, use `-I<prefix>/include -L<prefix>/lib -llzma` and a suitable
application RUNPATH, or select `<prefix>/lib/pkgconfig/liblzma.pc`. The installed
CMake package exports `liblzma::liblzma`; upstream recommends
`find_package(liblzma REQUIRED CONFIG)`. The static archive is also installed and
has its own executable API probe. Native checks record the actually loaded
library path, so an unrelated host library cannot satisfy them.

## Why this complete binary profile has a fixed prefix

Upstream `tuklib_gettext_init` passes the build-time absolute `LOCALEDIR` to
`bindtextdomain`. The locked CMake build has no complete relocatable-NLS switch.
Making an English command run after moving it would not establish that its
translated messages still work. This recipe keeps NLS and upstream source intact,
and declares a **fixed-prefix binary**. It does not inject a loader shim, alter
gettext, or silently remove translations.

Choose the eventual container path before building. For example, inside a build
container where the chosen prefix is writable and unoccupied, from the complete
workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 resource-integrations/v0180/worker-a/replay.py xz \
  --definitions compiler-playground/resources/packages \
  --output /work/cpg-build-xz-5.8.4 \
  --cache /work/cpg-download-cache --jobs 2 \
  --prefix /opt/compiler-playground/packages/xz/5.8.4
```

Before adoption, replace `--definitions` with
`resource-integrations/v0180/worker-a/packages`. The final batch entry passes the
single active mainline definition directory and may supply the selected prefix.
The command does not choose or write a host `/opt` path automatically. A custom
prefix cannot be combined with `--cleanup`; its live installation remains under
normal package-manager ownership until explicitly removed by its developer.

The resulting binary manifest records the exact selected prefix. Installation at
another path must fail before copying files. Separate containers can be configured
to use the same path while keeping independent filesystem copies; that deployment
is a separate container qualification, not an assertion made by this host replay.
The committed qualification artifact uses its actual evidence-directory prefix and
is evidence of the process, not a binary silently retargeted to `/opt`.

## Build prerequisites and recipe

Declared exact prerequisites are:

| Phase | Existing wrapper | Version |
| --- | --- | --- |
| Build | `apt.build-essential` | `12.10ubuntu1` |
| Build | `apt.cmake` | `3.28.3-1build7` |
| Build | `apt.ninja-build` | `1.11.1-2` |
| Build | `apt.gettext` | `0.21-14ubuntu2` |
| Checks | `apt.python3` | `3.12.3-0ubuntu2.1` |

Ubuntu base shell/grep/diff/sed utilities are needed by the upstream tests and
installed shell tools. The functional check records the actual utilities used;
their complete APT closure is not certified by that observation. Interactive
`xzless` additionally needs a pager such as `less`; interactive pager sessions are
not included in the automated qualification.

The recipe uses the upstream supported CMake/Ninja path with Release `-O2`, POSIX
threads, every default encoder/decoder/check/filter, all tools/scripts, NLS and
basic docs. It builds the shared library, CLI tools and official tests, runs the
complete configured CTest list, installs them, then builds the same-source static
library and installs it beside the shared library. It compiles separate probes
against the actually installed shared and static APIs. Upstream source files are
not patched. The full command logs, CTest XML, test discovery output and both
actual CMake caches are retained.

On the qualification host the exact CMake/Ninja releases were absent. The
maintainer replay therefore uses explicit build-only bindings to independently
extracted existing locked Ubuntu `.deb` files. It verifies each archive's
SHA-256/length/identity, records each executed tool and loaded library, and checks
that the dpkg database did not change. This is not an APT installation or an exact
APT closure claim. Normal environment deployment may use the declared exact APT
wrappers instead. Raw downloads are the only shared cache.

The locked Git snapshot includes all `po` and `po4a` translation inputs, but unlike
an upstream release tarball it has no pre-generated translated man pages. Upstream
CMake explicitly documents the separate `po4a/update-po` generation step. There is
no existing `apt.po4a` resource ID in this catalog, so this integration adds no ID:
translated `.mo` messages are built and exercised, English source man pages are
installed, and translated man-page generation is recorded as `not_run`. All
original translation sources remain available for developer-selected generation.

## Explicit source, binary and material packing

From the project directory:

```sh
cpg packages pack resources/packages/xz/package.json --definition --method source \
  --source xz=/path/to/exact-locked-archive --recipe resources/packages/xz/recipe \
  --output xz.source.cpgpkg.tar.gz
cpg packages install xz.source.cpgpkg.tar.gz --state /work/cpg-state \
  --cache /work/cpg-download-cache --prefix /opt/compiler-playground/packages/xz/5.8.4 --jobs 2
cpg packages check xz --state /work/cpg-state --prefix /opt/compiler-playground/packages/xz/5.8.4
cpg packages pack resources/packages/xz/package.json --definition --method binary \
  --payload /opt/compiler-playground/packages/xz/5.8.4 \
  --prefix /opt/compiler-playground/packages/xz/5.8.4 \
  --recipe resources/packages/xz/recipe --output xz.binary.cpgpkg.tar.gz
cpg packages pack resources/packages/xz/material-profile.json --definition --method material \
  --payload /path/to/full-verified-source --output xz.material.cpgpkg.tar.gz
```

Do not add `--relocatable` to this full XZ profile. Material installation preserves
the entire original payload and verifies its inventory; executable checks remain
`not_run`. The alternate definition is an active use of an existing CLI option,
not an inert backup or a new resource ID.

## Qualification contract

The replay checks source build/install, original material pack/install/inventory,
and fixed-prefix binary recovery. Before recovery it verifies the binary rejects
an incorrect prefix, explicitly removes its own source installation, then installs
the retained binary back at the same prefix. It compares the complete payload
inventory, reruns all declared checks and exercises mutation detection. It reports
different-prefix relocation as `not_applicable`.

Installed checks cover:

- Exact CLI/liblzma version agreement; fixed CRC32/CRC64 vectors; 45
  length/preset/check combinations for each shared/static linkage; damaged and
  truncated stream rejection; memory-limit and invalid-preset rejection.
- Raw x86+LZMA2 filter round trips and the two-thread encoder API for both linkage
  forms; CLI CRC32/CRC64/SHA256 at presets 1, 6 and 9 with two-thread blocks.
- XZ and LZMA-Alone interoperability with the observed host Python lzma binding;
  file/block robot output; xzdec/xzcat/lzmadec/lzcat/lzmainfo; actual xzgrep/xzdiff
  reading and difference detection.
- Real German help from both xz and lzmainfo under an actually installed non-C UTF-8 locale, matched to the
  package's installed catalog, rather than merely checking that a `.mo` file exists.

The actual pass/fail status and source/recipe/core hashes are in `review.json` and
the referenced qualification summary. This is not a performance measurement,
sanitizer/cross-architecture matrix, APT transaction or OCI deployment result.

For local qualification without a custom prefix, `--cleanup` may be added to the
replay when its output is a fresh worker evidence directory. It saves every
per-file inventory, source lock, CPG, build/check log and receipt before removing
only that run's rebuildable trees in the same process. Installation receipts then
describe a historical event, not a currently live prefix.
