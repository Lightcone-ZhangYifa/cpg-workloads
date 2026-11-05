# DejaGNU 1.6.3 source and harness-format reference

Resource: `dejagnu-source`, version `1.6.3`, build `2`, package type `material`.

This package retains the complete official DejaGNU source release: 189 ordinary files, 2,432,796 source bytes, framework and board scripts, tests, manuals and original per-file notices. It also installs the exact original `dejagnu-1.6.3.tar.gz` archive: 622,059 bytes, SHA-256 `87daefacd7958b4a69f88c6856dbd1634261963c414079d0c371f589cd66a2e3`.

## Installed contents

- `sources/dejagnu/`: the complete unmodified upstream source tree.
- `original-inputs/dejagnu-1.6.3.tar.gz`: the exact official archive for independent byte comparison.
- `share/cpg-material/README.md` and `share/licenses/LICENSE.CPG`: package guidance and the license for the authored integration helpers.

The retained availability check compares every installed source file with the original archive and rejects missing, changed or extra source files. It does not install a second executable harness. `apt.dejagnu` remains the original strict system dependency; the existing APT package and its frozen version are reused without changing its definition or publishing a duplicate wrapper.

## Qualification and use

This build was generated with the official CPG `pack` API after quick static review of a trusted delivery. Build, installation, functional execution and an independent rebuild are **not run under this artifact identity**. Earlier installation attempts were blocked by the original missing `apt.dejagnu` prerequisite; they do not establish installation success for this build.

The package is reference material for board integration, summary parsing and harness debugging. It does not claim a GCC regression run, a new functional qualification, a benchmark, or a new resource identity. The original catalog, provider, source lock, target and dependency fields are retained.

The repository also preserves `tools/probe_source_parser.py` and 15 synthetic `.sum` fixtures from the delivery. This optional helper evaluates selected source-format routines through a Python/Tcl bridge and calls the supplied CPG parser. It is not part of installation and was not rerun for this publication. Its contexts are explicitly synthetic. Running it requires Python with Tk/Tcl, AWK and an explicitly supplied CPG API root.

## Rebuilding this artifact

The complete editable source master and frozen package metadata are in this directory. The compressed upstream input is fetched only from its immutable source lock during publication; it is not stored in Git.

With the official CPG Python API and the exact upstream archive available locally:

```sh
python3 packages/dejagnu-source/rebuild_material.py \
  --archive /prepared/dejagnu-1.6.3.tar.gz \
  --output /absolute/new/dejagnu-source.material.cpgpkg.tar.gz
```

The helper only assembles the known local files, calls official `pack`, and compares the resulting artifact identity. It does not run DejaGNU, GCC, installation hooks or parser fixtures.

## Licenses

All upstream notices remain in place. `source/dejagnu-1.6.3/COPYING` contains the GPL v3 text; `doc/fdl.texi` and `doc/dejagnu.texi` preserve the documentation license and no-invariant-sections statement. Additional per-file terms are retained. `license-index.json` points to 17 notice-bearing files and is an index rather than a replacement license. Original catalog license identity remains `GPL-3.0-or-later AND GFDL-1.3-no-invariants-or-later AND LicenseRef-Per-File`. Authored CPG helpers are covered separately by `LICENSE.CPG`.
