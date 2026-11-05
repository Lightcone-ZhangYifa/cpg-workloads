# ClangIR compiler SDK subset

Package: `llvm-sdk.clangir` / `clang-trunk-20261101` / build `1` / type `binary`.

This is a byte-preserving, Linux x86_64 SDK subset from upstream llvm-project commit `ccc56cc44dedcf13c553508e198ddc8ec1aaff95`. Its parent software family is `llvm-release`; it does not replace the existing complete LLVM source package or add a new upstream compiler family.

## Included software

The separately pinned CIR-enabled clang compiler, cir-opt, cir-translate and required builtin resources. It is a supplemental llvm-project snapshot, not the original 23.1.4 compiler.

The original archive is `clang-trunk-20261101.tar.xz` (1,503,130,568 bytes), SHA-256 `db3c806443bd45210027758d4e46fe80e6139aa59852036545305b443face685`. `source-lock.json` retains its exact source URL and commit. The frozen artifact manifest lists each selected payload byte and link. `binary-sources.json` maps the selected upstream members for deterministic publication without storing the binary SDK in Git.

## Use with Clang capability materials

Install this binary package into its own prefix. The binary carries a relocatable maintainer declaration inherited from the trusted delivery; current installation and relocation checks have not been rerun. It requires the normal Linux x86_64 host ABI and relevant system libraries. The capability examples additionally need Python 3.12+, host C/C++ standard headers and linker, glibc, libstdc++, libgcc and zlib.

`llvm-feature.clang-and-clang-tools` supplies the separate `material` package with the Python API, semantic C++ rewrite helper and fixtures. Bind a prepared `llvm-sdk.clang` prefix explicitly to that material's existing `llvm-release` dependency role; its immutable input file lock verifies the required subset. Supply a prepared `llvm-sdk.clangir` prefix via `CPG_CLANG_CIR_ROOT`. The two source pins remain distinct and must not be substituted for one another.

This subset does not claim the complete LLVM tool suite, full upstream source-material qualification, a full regression suite, or a performance benchmark.

## Publication status

The current package was generated with the official CPG `pack` API after quick static review of the trusted delivery, source identity and distributed license texts. Build, installation, functional execution, native runtime checks and an independent rebuild are **not run** under this new artifact identity. Declared version commands are available for a consumer's explicit check.

LLVM and Clang copyright/license notices and the CPG MIT license accompany the installed payload in `share/licenses/`. The only source changes to the retained SDK are omission of prior preparation-result sidecars and addition of neutral package documentation and source locks. Compiler and header bytes are preserved.
