# CPG worker011：LLVM 优化诊断、评测协议与稀疏方言参考材料

本包完成资源大表中 worker011 的四项静态资产：OpenMP 优化说明、LLVM Optimization Remarks、LLVM test-suite Guide、MLIR Sparse Tensor Dialect。四项都固定在 LLVM **20.1.8**，提交 **`87f0227cb60147a26a1eeb4fb06e3b505e9c7261`**。使用者可以离线检索章节、命令行参数、API 和方言操作，并沿行号回到未经改写的上游原文。

这里的“材料完成”只表示固定版本原文、许可、索引及离线读取经过核验。它不增加原 1862 项资源的管理计数，不授予 LLVM 或 MLIR 功能资格，也不表示官方 test-suite 或 GPU 已运行。

## 1. 四项材料的实际范围

| 原任务 / entity_id | 本包内容 | 对 AI 开发编译器的用途 |
|---|---|---|
| `reference.doc.openmp-opt` | OpenMP 优化概览、aware/unaware 子章、命令行参数、该版本全部 OpenMP remarks 文档 | 在修改 OpenMPOpt 前定位优化条件，区分运行时调用消重、globalization 和诊断原因；按 remark ID 查到原文 |
| `reference.doc.llvm-remarks` | 完整 Remarks 文档、llvm-remarkutil 指南、同提交 C/C++ Remarks API 定位源文件 | 理解 passed/missed/analysis 事件及序列化字段，设计保留 pass/name/location/arguments 的证据记录 |
| `reference.doc.llvm-testsuite` | 完整 TestSuiteGuide 源文档 | 构造正确的评测协议和配置；识别编译、运行、结果比对与外部输入各自的条件 |
| `reference.doc.mlir-sparse` | SparseTensorOps ODS 原文及递归 TableGen include 闭包；属性、类型、接口、verifier 和 pass 定义定位材料 | 查看稀疏操作的参数、约束、示例和验证逻辑，帮助编写及审查 IR 改动 |

OpenMP 概览在上游很短，因此同时收录其两个子章和全部 remark 章节，避免只交一个目录入口。`OpenMPUnawareOptimizations.rst` 本身主要是上游报告链接；本包如实保留原文，不把这些视频误称为已下载材料。

SparseTensorOps 在此版本由 `mlir-tblgen -gen-dialect-doc` 生成，仓库没有同名静态 Markdown。本包提供真正的 `SparseTensorOps.td`、37 个 `sparse_tensor.*` 操作的准确定位、完整 literal include 闭包，以及记录生成规则的 `CMakeLists.txt`。没有运行 `mlir-tblgen`；`indexes/sparse-operations.json` 是本包生成的定位索引，不能描述为官方生成 HTML。TableGen 包含闭包不等于完整 C++ 构建闭包。

## 2. 离线使用

以下命令从安装后的材料根运行。Python 3.10 或更新版本即可，只用标准库。`-B` 避免生成未登记的 `__pycache__`。

```bash
python3 -B reference_library.py verify
python3 -B reference_library.py list
python3 -B reference_library.py chapters --asset reference.doc.mlir-sparse
python3 -B reference_library.py search globalization --asset reference.doc.openmp-opt
python3 -B reference_library.py search Hotness --asset reference.doc.llvm-remarks
python3 -B reference_library.py search TEST_SUITE_BENCHMARKING_ONLY --asset reference.doc.llvm-testsuite
python3 -B reference_library.py search sparse_tensor.convert --asset reference.doc.mlir-sparse
python3 -B reference_library.py read mlir/include/mlir/Dialect/SparseTensor/IR/SparseTensorOps.td --line 157 --count 55
```

部署时应从外部已核对的交付回执或 CPG recipe 获取 `inventory.json` 的 SHA-256，并将它传入 `--expected-inventory-sha256`。不要把刚从待验证包读取的值当成外部信任依据。

```python
from reference_library import ReferenceLibrary

library = ReferenceLibrary("/absolute/reference/prefix",
                           expected_inventory_sha256=TRUSTED_INVENTORY_SHA256)
hits = library.search("sparse_tensor.convert",
                      asset_id="reference.doc.mlir-sparse", limit=8)
result = library.read(hits[0]["upstream_path"], line=hits[0]["line"], count=30)
```

检索按不区分大小写的字面子串匹配，不把用户输入解释为正则、shell 或代码。结果提供原文件、行号、SHA-256 和固定提交的 GitHub 定位链接。链接方便联网查阅；离线查询本身只读本地已验证字节。`chapters` 同时返回章节和符号定位，`kind` 字段区分 RST/Markdown 章节、字面标识符、TableGen 定义、稀疏操作及源文件定位符；普通源码定位不是 C++ 语义索引。

## 3. 推荐的开发动作

**OpenMP 优化审查。** 先按已观察到的 remark ID 或 pass 名检索，读出对应条件和上下文，再检查待修改 IR。材料可解释优化条件；是否在目标工具链触发、是否正确、是否更快，需要独立程序与目标环境证据。

**优化诊断归档。** 使用 Remarks 文档确认字段和事件类型，再设计输出记录。不能把 “passed” remark 当作语义证明，也不能把 “missed” 当作性能回归结论。资料包没有实际运行 remark 生成器或 parser。

**官方评测准备。** 依据 TestSuiteGuide 明确配置、输入、编译及计时协议。本包不包含 test-suite 程序、External 语料和性能结果；它也不改变工程现有 Dataset 接口的资格。官方 benchmark 与源码 Dataset 必须分别记账。

**稀疏 IR 修改。** 从 `sparse_tensor.*` 操作索引进入同版本 ODS，核对操作 traits、类型/属性和 description，再查 `SparseTensorDialect.cpp` 的 verifier 定位。pass 声明可帮助确定需要的流水线入口，但声明和源码材料本身不证明 lower、runtime 或硬件已运行。

## 4. 来源、许可与完整性

全部上游原文来自固定提交的 `raw.githubusercontent.com/llvm/llvm-project/…`。准备阶段另外读取 LLVM 官方 Gitiles 镜像的提交及目录树：重新计算每个目录 Git tree SHA-1，核对父目录链到提交根 tree，再逐个核对 Git blob SHA-1。每个原文件还记录字节数与 SHA-256。原始树响应保存在 `evidence/upstream/`，不会被部署阶段联网刷新。

`materials/source-manifest.json` 给出各资产对应文件、固定 URL、许可、下载身份和 49 条 TableGen include 边。项目根及 LLVM、MLIR、OpenMP 的原许可证完整保留。`NOTICE` 说明未修改上游字节；本包自身辅助代码和原创说明采用 MIT，第三方内容继续适用其原许可。

离线 reader 首先验证显式 `inventory.json`，再验证源文件清单、Git blob、include 边、索引行范围及资产 ID。缺失文件、字节变化、符号链接、硬链接及未声明额外文件都会拒绝。只允许 CPG 管理器在根目录加入精确名 `.cpg-prefix.json` 的状态文件，不豁免任何上游、索引或脚本路径。摘要用于绑定字节，不能证明编译语义正确。

## 5. 重建与资格边界

外层 `tools/prepare_sources.py` 是明确联网的准备入口。它固定版本，不自动转到最新版本，不在读取/部署时下载缺失内容。`tools/build_payload.py` 只使用本地已校验材料构建新目录；`tests/validate_reference.py` 执行离线检索与完整性负例。最终真实测试结果见外层 `evidence/validation.json`。

交付结果采用 `worker-results.jsonl` 的统一字段。四行 `after_material=true` 仅对应 `reference_asset`；`after_functional` 和 `after_dataset_verified` 保持 `null`。原目录、版本、依赖、catalog 摘要及原 null 字段不修改。本包使用原来的 Python library-first 工程接口，不触及 Experiment/Trainer、SourceGrad、模型部署政策或定时任务。
