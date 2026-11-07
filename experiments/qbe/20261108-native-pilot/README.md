# Real QBE native pilot, 2026-11-08

These source patches preserve the compiler and regression-test changes from two
real Codex trials. They are experiment artifacts, not revisions of the active
QBE package, qualified releases, or claims of general optimization benefit.
The original upstream QBE license is retained in `QBE-LICENSE`.

Start from exact QBE 1.3 raw archive SHA-256
`d587905d620dc5e1d2bfa7c2cc642b9b837aa89a3188c6e37b53d756cf66e320`,
281,332 bytes. The existing `qbe` source lock records its upstream URL.
Apply **one** patch to an independent clean extracted source directory:

```sh
git apply --check /path/to/sol-data-driven.patch
git apply /path/to/sol-data-driven.patch
```

`patch-verification.json` records the patch hashes and every changed file hash.
Both patches were applied to independent baseline extractions and all resulting
changed file bytes were checked against their actual recorded trial commits.
The patches omit the agents' `research/` directories, which remain in their full
local Git histories. Consequently applying a patch reproduces the compiler and
test files, not the original candidate's entire Git commit or its self-reported
research evidence.

| Trial | Model / loop | Actual candidate commit | Controller result |
| --- | --- | --- | --- |
| `sol-data-driven` | gpt-6.1-sol / data-driven | `8d8bcb7ee9a7b19f466618e1709f3c6dc90f3144` | Frozen upstream gate and bsort mathematical oracle passed; retained as incumbent |
| `terra-simple` | gpt-6.1-terra / simple | `a51290653683a58d908c4902e4189a0e2a72f8b7` | Gate passed; validation did not improve, so baseline remained incumbent |

The Sol patch fixes recursive instruction sinking in `gcm.c` and adds a
regression test. Three confirmation sessions of the original three bsort cases
observed equal-weight runtime reductions of 4.203%, 4.285%, and 4.324%. All used
the same machine and frozen artifacts. Training and validation overlap was
recorded. This is one program family with no physical isolation or unseen-data
qualification. The matched original CoreMark performance and validation runs
were valid, but their single observed score increase is not statistical evidence.

The Terra patch changes constant division/remainder handling and adds tests.
Its independent controller result is retained despite failing to improve the
validation score. The trials use different models and loops and do not form a
fair experimental comparison of those treatments.

To rebuild, admit, train and independently benchmark using the framework, see
[`docs/minimal-native.md`](https://github.com/Lightcone-ZhangYifa/compiler-playground/blob/development/local-validation/docs/minimal-native.md).
The complete result, immutable image, source identities, cost limits, original
receipt hashes and figure are in
[`docs/local-validation-20261108.zh-CN.md`](https://github.com/Lightcone-ZhangYifa/compiler-playground/blob/development/local-validation/docs/local-validation-20261108.zh-CN.md).
The controller's original frozen upstream test suite remains the baseline suite;
candidate-authored tests are separate additional evidence.
