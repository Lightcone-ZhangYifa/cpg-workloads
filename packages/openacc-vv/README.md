# OpenACC Validation and Verification

Resource `openacc-vv`, upstream commit/version `48d8b854280bfbd0294fea79668fdf2dd9386305`, software build `1`.

## Separate downloadable package types

| Type | Contents and installation behavior |
| --- | --- |
| `source` | The exact original upstream archive plus the frozen CPG installation recipe, inventories and adapter. Selecting source installation explicitly permits its declared preparation/build commands. |
| `binary` | A prepared Python harness and original test-source installation tree. The binary package type denotes a ready deployment tree; it does not mean that every compiler test is precompiled. |

Both types keep the same software ID, commit, target and neutral build. The original archive is locked to `13953b271e9574aab19e274ba0bd0aaa098dd6d7295122b34a4f787bfc62f8e0` (572,114 bytes) in `source-lock.json`. The full original sources and upstream notices are retained without compatibility patches. Authored integration files live in the separate recipe and installed adapter locations.

## Bounded host profile

The complete inventory contains 1,341 test sources: 441 C, 455 C++ and 445 Fortran. The delivered GNU 13 / OpenACC 2.6 host core profile selects 24 C/C++ files. Its historical evidence reported 21 successful compile/run cases and 3 compile failures (parallel_if.cpp, routine_seq.c and routine_seq.cpp). Those failures remain compiler results, not passing conformance tests. Other tests, Fortran, GPU devices and other specification versions were not covered by that bounded run.

These are historical scope facts from the trusted input delivery. The newly named artifacts have **not been built, installed or functionally executed**. In particular, adapter-result collection is not equivalent to complete compiler conformance, GPU validation or a performance claim. No Dataset or official benchmark qualification is added by publication.

The explicit target is Linux x86_64 with no distribution whitelist. The host checks require the supplied GNU/OpenACC profile and appropriate host commands. EPCC uses Python and GCC; V&V also needs G++ for the selected C++ cases. A separately provided Fortran compiler is needed when explicitly selecting Fortran tests. Package installation does not download or solve missing host-tool dependencies.

The original declared `host-functional` check remains available for a consumer's explicit run. Use a fresh work directory outside the installation prefix. V&V's `status=completed` means that result collection completed; compiler and run failures remain failures in the collected records.

## Source master and publication

`package.json`, `source-lock.json`, `recipe/`, `artifact-locks.json` and the frozen templates define these downloads. The `source` package contains the unmodified, byte-locked upstream archive. The `binary` package is repacked from the trusted prepared installation tree; the existing EPCC executable bytes are preserved. Only delivery-assignment labels in authored comments/temporary names, public metadata and the missing CPG license distribution were corrected. No native build, installation or regression suite was run to make these artifacts.

The official CPG `pack` API generated both package types. The existing static admission path parsed metadata and recipe syntax without executing recipes. Publication transfers the exact frozen artifact bytes and uses the repository's single release implementation.

## Licenses

The original upstream license and third-party notices remain inside the locked upstream sources and installed tree. The original delivery's license statement is: BSD-3-Clause; bundled third-party viewer notices preserved. Authored CPG adapter and installation code is accompanied by the repository MIT license in `recipe/LICENSE.CPG` and in the installed software's share directory. Original copyright and attribution notices are retained.
