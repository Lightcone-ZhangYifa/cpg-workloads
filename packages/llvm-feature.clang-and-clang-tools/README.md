# Clang tooling, clangd and CIR capability materials

Resource: `llvm-feature.clang-and-clang-tools`, version `llvmorg-23.1.4`, build `2`, package type `material`.

This package contains the C++ semantic rewriting helper, its Python API, an LSP client, fixtures, immutable SDK file locks, and declared CPG checks. It uses the existing Clang resource identity and does not include a second copy of the LLVM toolchain.

## Exact inputs and scope

The LibTooling, ASTMatchers, Transformer and clangd examples bind LLVM commit `7a941dfb2877a0b8cf30323fefa85ad019e0b0f5` (23.1.4). The original binary build has CIR disabled. CIR requires the separately pinned Compiler Explorer `clang-trunk-20261101` build of upstream llvm-project commit `ccc56cc44dedcf13c553508e198ddc8ec1aaff95`; it does not replace the original catalog pin.

The declared tasks are a two-call-site, type-qualified C++ rewrite, clangd diagnostics and cross-translation-unit navigation, and C to CIR to LLVM IR to native execution for a small fixture. These are bounded capability examples, not complete LLVM regression coverage or a performance benchmark. Carrying this package does not establish complete LLVM source-material qualification.

## Software downloads and explicit SDK bindings

`llvm-sdk.clang` supplies the Linux x86_64 Clang tooling SDK subset at the original pin. `llvm-sdk.clangir` supplies the separate CIR compiler subset. Both are explicit subsets of the LLVM software family. The original `llvm-release` package remains the full LLVM source definition.

This material preserves its existing `llvm-release` dependency declaration. A caller may explicitly bind that dependency role to a prepared, byte-matching Clang SDK subset prefix; the recipe checks every required file against `recipe/toolchain-bindings.json`. This is an explicit local path binding, not an implicit replacement of the registry's full `llvm-release` resource. Supply the separate CIR prefix with `CPG_CLANG_CIR_ROOT`.

```python
receipt = manager.install(
    artifact_path,
    prefix=material_prefix,
    dependencies={'llvm-release': {'prefix': '/prepared/clang-sdk'}},
    environment={'CPG_CLANG_CIR_ROOT': '/prepared/clangir-sdk'},
)
```

The runner can also be invoked directly from the installed material prefix:

```sh
python3 -B clang_capabilities.py --llvm-root /prepared/clang-sdk \
  --cir-root /prepared/clangir-sdk \
  --cir-pin ccc56cc44dedcf13c553508e198ddc8ec1aaff95 \
  --output /absolute/new/clang-capability-run
```

`clang_capabilities.validate(...)` exposes the same Python entry point. The runner does not download or solve dependencies. Its declared execution prerequisites include Python 3.12+, normal host C/C++ headers and linker, glibc, libstdc++, libgcc and zlib. The inherited target metadata records Linux x86_64 on Ubuntu 24.04; it does not claim validation on additional hosts.

## Current publication status

This artifact is published from a trusted delivery after a quick static review of its identity, locks and licenses. Build, installation, functional execution and fresh rebuilding were **not run under this new artifact identity**. Existing declared checks are retained for an explicit consumer run. The previous delivery's execution results are not reassigned to this artifact's hash.

The source changes replace delivery-assignment names with software names, add the distributed license texts, and retain the capability implementation and original source pins. Upstream LLVM and Clang license texts and the CPG MIT license are in `licenses/`.
