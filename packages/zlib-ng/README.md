# zlib-ng 2.3.3 resource maintenance

This existing resource ID provides three explicit installation methods. The source
and binary profile uses the upstream default **native ABI** (`zlib-ng.h`, `zng_*`
and `libz-ng`), allowing it to coexist with system zlib. The exact original
`material-profile.json` retains every upstream source, test and reference file,
including the alternative zlib-compatible ABI build support. Its source lock and
`metadata.catalog` are unchanged.

## Discover and use

Start with `cpg packages info zlib-ng --json`, `cpg packages paths zlib-ng`, and
`cpg packages check zlib-ng --prefix <prefix>`. These commands use the active
package definition and actual receipt. Select the prefix explicitly when several
copies are present.

The native headers are in `<prefix>/include`; shared and static libraries are in
`<prefix>/lib`. The upstream minigzip utility is installed as
`<prefix>/bin/zlib-ng-minigzip` to avoid changing the system gzip command.
`<prefix>/share/compiler-playground/zlib-ng` contains the upstream license,
README/PORTING guide, actual configure log, example sources and installed probes.
The source installation additionally preserves the entire original tree under its
receipt's `assets/corpora/zlib-ng` directory. A binary-only install does not
silently fabricate that source directory.

The native gzip file declarations require `-DWITH_GZFILEOP`; the upstream
`zlib-ng.pc` supplies this flag. For example:

```sh
export PKG_CONFIG_PATH="<prefix>/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
cc program.c $(pkg-config --cflags --libs zlib-ng) -Wl,-rpath,<prefix>/lib -o program
<prefix>/bin/zlib-ng-minigzip -6 < input.bin > input.gz
<prefix>/bin/zlib-ng-minigzip -d < input.gz > restored.bin
```

Without pkg-config, use `-DWITH_GZFILEOP -I<prefix>/include -L<prefix>/lib -lz-ng`
and an appropriate application RUNPATH. `libz-ng` does not replace `libz.so`.
No global `ldconfig`, `LD_PRELOAD` or shared installation tree is required.

## Build and package

The declared build prerequisite is the existing exact
`apt.build-essential=12.10ubuntu1` wrapper. The declared system prerequisite for
checks is `apt.python3=3.12.3-0ubuntu2.1`. Their database identities are checked;
the observed compiler and runtime hashes are also retained. No APT transaction is
performed by this replay.

The recipe copies the locked source into a private build tree, runs upstream
`configure --shared`, `make all`, `make test`, `make infcover` and `./infcover`,
then installs both library forms. It uses upstream optimized dispatch defaults,
`-O2 -g0`, and no added `-march=native`. Upstream target-specific flags remain in
effect. The install-time loader-cache hook is disabled because the probes use a
relative RUNPATH. Only the installed pkg-config prefix is made relative; the
upstream source is not edited.

From the complete workspace root, before adoption:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 resource-integrations/v0180/worker-a/replay.py zlib-ng \
  --definitions resource-integrations/v0180/worker-a/packages \
  --output resource-integrations/v0180/worker-a/evidence/zlib-ng/my-fresh-run \
  --cache resource-integrations/v0180/download-cache --jobs 2 --cleanup
```

After adoption, pass `--definitions compiler-playground/resources/packages`.
This is the single active definition directory used by the final maintainer batch
entry. The replay outputs relative artifact paths, SHA-256 and byte lengths in
`summary.json`; it never calls a system installer.

The equivalent explicit packing operations are:

```sh
cpg packages pack resources/packages/zlib-ng/package.json --definition --method source \
  --source zlib-ng=/path/to/exact-locked-archive --recipe resources/packages/zlib-ng/recipe \
  --output zlib-ng.source.cpgpkg.tar.gz
cpg packages pack resources/packages/zlib-ng/material-profile.json --definition --method material \
  --payload /path/to/verified-full-unpacked-source --output zlib-ng.material.cpgpkg.tar.gz
cpg packages pack resources/packages/zlib-ng/package.json --definition --method binary \
  --payload /path/to/checked-prefix --recipe resources/packages/zlib-ng/recipe --relocatable \
  --output zlib-ng.binary.cpgpkg.tar.gz
```

These are two definitions of the same resource ID, selected with the existing
`pack --definition` interface, without adding a new profile framework or resource
ID. A material install has no executable checks: `not_run` is the correct status,
while complete payload integrity is verified independently.

## Actual qualification and limits

`evidence/zlib-ng/qualification-2/summary.json` records the passing event:

- Official `make test` exercised static/shared examples and upstream regressions;
  upstream `infcover` also ran successfully. This is execution evidence, not a
  claimed gcov percentage.
- Installed shared and static native API probes each passed 15 length/level
  combinations, fixed CRC32/Adler32 vectors, truncation/corruption rejection,
  dictionary round trips and wrong-dictionary rejection, two-chunk streaming, and
  actual gzip file IO.
- Python's independent gzip/zlib implementation checked gzip streams in both
  directions at levels 1, 6 and 9. Damaged CRC trailers were rejected.
- Source and two binary installations had equal payload inventories and different
  file inodes. Modifying one copy was detected without affecting the others.
  A separate regression restored the retained binary to a new temporary prefix and
  reran its real checks. Corrupting its selected shared library caused failure.

The first qualification preserved an actual failed probe compilation because
`WITH_GZFILEOP` was missing; the fix follows the upstream header and pkg-config
contract. That failed run and its artifacts/logs remain available.

The full CMake/GoogleTest, sanitizer, cross-architecture and alternative compat ABI
matrices were not run. No benchmark timing, APT transaction, OCI deployment or
separately reconstructed toolchain reproducibility is claimed. Relocation is
qualified only for this Ubuntu 24.04 x86_64 native profile on the observed host.

The replay's optional `--cleanup` records complete per-file inventories and hashes
the retained evidence before removing its own rebuildable trees in the same
process. Original locks, source/material/binary CPGs, recipe logs, check output and
receipts remain. These receipts describe the historical qualification event and
do not claim that cleaned prefixes are still installed.
