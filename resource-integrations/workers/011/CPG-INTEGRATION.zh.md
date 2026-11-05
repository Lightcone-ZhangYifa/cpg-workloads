# worker011：CPG 0.21.14 集成与交接

worker011 的四项参考资产已通过原工程 `PackageManager` 的真实安装、查询、完整性检查、独立副本隔离和移除验证。交付包含 **1 个 `material` 容器包、4 个独立 reference entity**；材料可用性检查为 `passed`，工具功能资格 **F 保持 `not_run`**。原始 **1862** 项资源目录及其摘要保持不变，旧资源计数增量为 **0**。

本说明使用已有的 Python library-first 接口及其 `cpg packages` 薄 CLI；`tools/replay_package_lifecycle.py` 只是调用原接口的验收驱动。材料的内容、来源、许可证、查询边界见 [README.zh.md](README.zh.md)；本次实际运行记录见 [evidence/cpg-lifecycle/summary.json](evidence/cpg-lifecycle/summary.json)。

## 1. 包身份、资产映射与运行条件

| Reference entity | 内容 | CPG 包 ID |
|---|---|---|
| `reference.doc.openmp-opt` | OpenMP optimizations 与 optimization remarks | `reference-pack.worker-011` |
| `reference.doc.llvm-remarks` | LLVM Remarks、remarkutil 与对应 API 原文 | `reference-pack.worker-011` |
| `reference.doc.llvm-testsuite` | LLVM TestSuiteGuide | `reference-pack.worker-011` |
| `reference.doc.mlir-sparse` | SparseTensorOps ODS、包含闭包与操作定位 | `reference-pack.worker-011` |

四项都固定到 `llvmorg-20.1.8`，提交 `87f0227cb60147a26a1eeb4fb06e3b505e9c7261`。共同载荷有 98 个普通文件、1,622,103 字节，其中包括 60 个未经改写的上游文件、1,432 条章节或符号索引，以及 37 个 sparse tensor 操作的定位。容器减少重复安装；统一结果文件仍保留四行 reference asset 结果，不把一份容器计为四个新增工具。

| 项目 | 固定值 |
|---|---|
| CPG 基线 | `0.21.14` |
| 包版本 / build | `2026.11.01.1` / `worker-011-v001` |
| provider / method / adapter | `material` / `material` / `copy` |
| 归档 | `cpg/artifacts/reference-pack.worker-011.material.cpgpkg.tar.gz` |
| 归档字节数 | `285416` |
| 归档 SHA-256 | `b33c0ea4fb1d480d5d30ad9847fad5c84bd7f2b8a47415ffa458e72837289174` |
| 归档 manifest SHA-256 | `7604ee9d1aad11d33901facd247eeaf102fc8a47ce4e95187cb8f9a14bfb6732` |
| 载荷 `inventory.json` SHA-256 | `979134ffdffc1cae9b48b8b72b2db036465f47ad23f653307a9f47fdfa04dac4` |
| 扩展 catalog 摘要 | `7716ac833b6e7513dacab0abddebdbac889bc890ccd41d66b19a7c0f50cfcfb7` |
| 原始 1862 项 catalog 摘要 | `61e29cc2aad359530721efa1ff64447502ef028f9966220a066c49dce5ca0f27` |

精确机器映射保存在 `cpg/package-index.json`，独立扩展注册表为 `cpg/registry.json`。扩展使用自己的包 ID，不覆盖默认注册表。各参考资产的上游许可与辅助代码 MIT 许可均随载荷保留。

集成检查及 replay 使用 Python 3.11 或更新版本，因为 CPG recipe/驱动使用 `hashlib.file_digest`；本次运行环境使用 Python 3.12.14。独立材料 reader 本身支持 Python 3.10 及以上。请在安装了 `compiler-playground==0.21.14` 的环境中运行下文，且让 `python3` 指向满足要求的解释器。验证现场的解释器为 `/workspace/scratch/7f487a211dd5/cpg-baseline/venv/bin/python`，CLI 为同目录下的 `cpg`。

注册表中的 Ubuntu 24.04 / x86_64 / Linux 记录验证主机；实际回执的 `platform_fields_checked=[]`，`distribution_policy=reference_build_metadata_not_an_installation_gate`。该材料包没有编译依赖、系统包安装或部署时联网下载步骤。这里的可移植性是静态材料与 Python 读取接口的范围，不增加其他平台已测证据。

## 2. 首选：已有 PackageManager 的 Python 接口

先把下面两个路径替换为解压后的 worker011 目录，以及一个**尚不存在**的验收工作目录。使用安装有 CPG 0.21.14 的 Python 执行代码；`-B` 防止向受保护的材料树写入 `__pycache__`。

```bash
export CPG_WORKER011_BUNDLE="/absolute/path/to/worker-011"
export CPG_WORKER011_RUN="/absolute/path/to/new/worker-011-api-run"
python -B - <<'PY'
import importlib.metadata
import json
import os
from pathlib import Path
import sys

from compiler_playground.packages import PackageManager, Registry, verify_package

if importlib.metadata.version("compiler-playground") != "0.21.14":
    raise RuntimeError("This example requires CPG 0.21.14")

bundle = Path(os.environ["CPG_WORKER011_BUNDLE"]).absolute()
run = Path(os.environ["CPG_WORKER011_RUN"]).absolute()
if run.exists() or run.is_symlink():
    raise FileExistsError("Use a fresh output directory")
run.mkdir(parents=True)

package_id = "reference-pack.worker-011"
archive = bundle / "cpg/artifacts/reference-pack.worker-011.material.cpgpkg.tar.gz"
registry = Registry.load(bundle / "cpg/registry.json")
baseline = Registry.load().to_dict()
verified = verify_package(
    archive,
    expected_sha256="b33c0ea4fb1d480d5d30ad9847fad5c84bd7f2b8a47415ffa458e72837289174",
    expected_bytes=285416,
)
if verified["manifest"]["package"] != registry.get(package_id):
    raise RuntimeError("The artifact and extension registry differ")

prefix = run / "prefixes" / package_id
manager = PackageManager(
    state=run / "state",
    prefix_root=run / "prefixes",
    cache=run / "cache",
    registry=registry,
)
record = manager.install(archive, prefix=prefix, check=True)
if record["installation"]["status"] != "installed":
    raise RuntimeError("Installation failed")
if record["checks"]["status"] != "passed":
    raise RuntimeError("The declared material checks did not pass")
if record["checks"]["availability_status"] != "passed":
    raise RuntimeError("Material availability was not verified")
if record["checks"]["functional_status"] != "not_run":
    raise RuntimeError("Unexpected functional qualification")
if manager.verify_installed(package_id, prefix=prefix)["status"] != "verified":
    raise RuntimeError("Installed inventory mismatch")

sys.path.insert(0, str(prefix))
from reference_library import ReferenceLibrary

library = ReferenceLibrary(
    prefix,
    expected_inventory_sha256="979134ffdffc1cae9b48b8b72b2db036465f47ad23f653307a9f47fdfa04dac4",
)
hits = library.search(
    "globalization", asset_id="reference.doc.openmp-opt", limit=4
)
if not hits:
    raise RuntimeError("The local query returned no source location")
excerpt = library.read(hits[0]["upstream_path"], line=hits[0]["line"], count=20)
material_check = manager.check(package_id, prefix=prefix, kinds=["availability"])
if material_check["status"] != "passed":
    raise RuntimeError("The repeated material check failed")

result = {
    "package_id": package_id,
    "checks": record["checks"],
    "material": library.verify(),
    "query": hits,
    "excerpt": excerpt,
}
(run / "query-result.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

# Remove only this explicit demonstration prefix after collecting the evidence.
manager.remove(package_id, prefix=prefix)
if prefix.exists():
    raise RuntimeError("The demonstration prefix survived removal")
manager.report(run / "report")
if Registry.load().to_dict() != baseline:
    raise RuntimeError("The original registry changed")
print(json.dumps({"status": "passed", "output": str(run), "prefix_removed": True}))
PY
```

此例完成安装、实际检查、离线查询、完整性验证及移除，输出目录保留 state 收据、日志、查询结果与报告。检查的是 `record["checks"]["status"]` 及具体资格字段，不能仅因安装状态为 `installed` 就推定检查已通过。程序如中途失败会保留现场供审查。

## 3. CLI：逐步安装与使用

本节提供另一条使用路径，可在单独的工作目录保留安装用于日常检索。CPG 0.21.14 将 `--registry` 和 `--state` 定义在各个子命令上，实际语法是 `cpg packages install --registry ...`。先激活已有 CPG 环境，再修改并设置以下路径：

```bash
export CPG_WORKER011_BUNDLE="/absolute/path/to/worker-011"
export CPG_WORKER011_RUN="/absolute/path/to/new/worker-011-cli-run"
export CPG_WORKER011_PREFIX="$CPG_WORKER011_RUN/prefixes/reference-pack.worker-011"
cd "$CPG_WORKER011_BUNDLE"

cpg packages list --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" --all --json

cpg packages verify --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" \
  cpg/artifacts/reference-pack.worker-011.material.cpgpkg.tar.gz \
  --sha256 b33c0ea4fb1d480d5d30ad9847fad5c84bd7f2b8a47415ffa458e72837289174 \
  --bytes 285416 --json

cpg packages install --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" \
  cpg/artifacts/reference-pack.worker-011.material.cpgpkg.tar.gz \
  --prefix "$CPG_WORKER011_PREFIX" \
  --prefix-root "$CPG_WORKER011_RUN/prefixes" \
  --cache "$CPG_WORKER011_RUN/cache" --json

cpg packages info --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" reference-pack.worker-011 \
  --prefix "$CPG_WORKER011_PREFIX" --recorded-only --json

cpg packages paths --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" reference-pack.worker-011 \
  --prefix "$CPG_WORKER011_PREFIX" --files --json
```

`install` 默认执行已声明的 availability 检查；本例保持该默认值。期待安装结果中的 `checks.status` 与 `checks.availability_status` 为 `passed`，`checks.functional_status` 为 `not_run`。

材料查询使用已安装前缀中的 reader。下面给出每项资产的可复现查询；reader 全局参数位于 `verify`、`search` 等子命令之前。

```bash
python3 -B "$CPG_WORKER011_PREFIX/reference_library.py" \
  --expected-inventory-sha256 979134ffdffc1cae9b48b8b72b2db036465f47ad23f653307a9f47fdfa04dac4 \
  verify
python3 -B "$CPG_WORKER011_PREFIX/reference_library.py" list
python3 -B "$CPG_WORKER011_PREFIX/reference_library.py" \
  search globalization --asset reference.doc.openmp-opt --limit 4
python3 -B "$CPG_WORKER011_PREFIX/reference_library.py" \
  search Hotness --asset reference.doc.llvm-remarks --limit 4
python3 -B "$CPG_WORKER011_PREFIX/reference_library.py" \
  search TEST_SUITE_BENCHMARKING_ONLY --asset reference.doc.llvm-testsuite --limit 4
python3 -B "$CPG_WORKER011_PREFIX/reference_library.py" \
  search sparse_tensor.convert --asset reference.doc.mlir-sparse --limit 4
python3 -B "$CPG_WORKER011_PREFIX/reference_library.py" \
  read mlir/include/mlir/Dialect/SparseTensor/IR/SparseTensorOps.td --line 157 --count 55
```

`verify` 校验归档；`verify-installed` 依据 CPG 收据验证实际安装树；reader 的 `verify` 校验材料、来源和索引。独立 reader 的外部 inventory 摘要应来自已核验的交付记录，上文使用本次冻结值。只读取待验证材料内的摘要，不能建立对共同改写清单与文件的外部约束。

继续运行下列命令可重复 availability 检查，输出安装报告，最后移除本节指定的安装前缀：

```bash
cpg packages check --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" reference-pack.worker-011 \
  --prefix "$CPG_WORKER011_PREFIX" --kind availability --json

cpg packages verify-installed --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" reference-pack.worker-011 \
  --prefix "$CPG_WORKER011_PREFIX" --json

cpg packages report --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" --output "$CPG_WORKER011_RUN/report-installed"

cpg packages remove --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" reference-pack.worker-011 \
  --prefix "$CPG_WORKER011_PREFIX" --json

cpg packages report --registry cpg/registry.json \
  --state "$CPG_WORKER011_RUN/state" --output "$CPG_WORKER011_RUN/report-removed"
```

移除后的收据状态为 `removed`，此前检查记录和日志仍保留。`--prefix` 精确选择本次安装，适合与其他独立工作目录并存。

## 4. 一条命令重放完整 A/B 生命周期

在安装了 CPG 0.21.14 的 Python 环境中，指定解压后的 bundle 及一个尚不存在的输出目录：

```bash
python -B /absolute/path/to/worker-011/tools/replay_package_lifecycle.py \
  --bundle /absolute/path/to/worker-011 \
  --output /absolute/path/to/new/worker-011-lifecycle-run
```

`--output` 必须是新目录，驱动会拒绝复用已有目录。执行会验证归档摘要及其包定义，使用不同 state/prefix 建立 A、B 两套安装，检查全部 98 个载荷文件字节相同且 inode 独立，再进行以下实际操作：修改 A 的一个文件并确认检测失败、确认 B 不受影响；修改 A 的一个 recipe 文件并确认原管理器在执行前拒绝；恢复字节并重新验证和检查；移除 A 后再次检查 B，最后移除 B。原始注册表在执行前后逐值比较。

驱动成功结束时写出 `summary.json`，保留两套安装与检查日志、收据和报告，两套演示 prefix 已移除。驱动失败时保留失败摘要和当前现场。该命令不需要 LLVM/MLIR 可执行文件或网络，也不会运行 test-suite、TableGen 文档生成器或硬件工作负载。

## 5. 本次真实证据及统计口径

真实执行目录为 `/workspace/scratch/7f487a211dd5/integration-validation/worker-011`，结果摘要复制到 `evidence/cpg-lifecycle/summary.json`。证据副本保留原始绝对路径、时间戳、stderr/stdout 和检查结果；日志中的绝对路径指向当时执行现场，不会因交付后换目录而被重写。`evidence/cpg-lifecycle-copy-manifest.json` 给出每个原文件与交付副本的路径、字节数和 SHA-256。重复的 `package/` 解包树与运行锁文件不纳入证据副本；所需载荷和 recipe 已由本包正式交付。

| 实际验证项 | 本次结果 | 证据 |
|---|---|---|
| 原 PackageManager 安装 A / B | 两次 `installed`；两次声明检查 `passed` | `summary.json` 的 `packages[0].installs` 与原安装 `checks.json` |
| 材料检查 | 98 个文件、1,622,103 字节及四项真实索引查询 | 四份 stdout 日志与相应 `checks.json` |
| A/B 独立性 | 98 个普通文件，0 个共享 inode | `independence` |
| 载荷篡改 | A 被检测，B 保持通过，恢复后重新核验通过 | `payload_tamper_detected`、`restored_inventory` |
| recipe 篡改 | 原管理器拒绝，原因为 `Installed package helper files changed: recipe` | `recipe_tamper_rejected`、`recipe_tamper_reason` |
| 先移除 A，再检查 B | B 的实际检查仍为 `passed` | `b_after_a_remove` |
| 最终移除 | A、B 前缀均移除，保留移除收据 | `removed_prefixes`、两份 state receipt |
| 资格 | availability `passed`；functional、hardware、version 均 `not_run` | 原始 `checks.json` |
| 原目录 | 1862 项、摘要未变、旧资源增量 0 | `baseline_resource_count`、`original_registry_unchanged` |

这些结果证明材料部署与本地读取。四项 `after_material=true`，`after_functional=null`，`after_dataset_verified=null`；没有增加 LLVM/MLIR 工具 F、Dataset、官方 benchmark、OCI 或硬件资格。SparseTensorOps 的 TableGen 定义与包含闭包已完整收录，但本次没有运行官方文档生成器，也没有执行稀疏 lowering/runtime。

此前材料本身的 25 项正负验证和离线可重建证据分别保存在 `evidence/validation.json`、`evidence/reproducibility.json`。新增的 CPG 容器、recipe、驱动、集成说明和原始运行证据已纳入 `evidence/delivery-file-selection.json`；最终统计见 `evidence/delivery-summary.json`。
