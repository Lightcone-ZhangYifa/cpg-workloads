egg 共享感知 ILP 提取参考材料

固定版本：0.11.0
上游提交：fb6167957beb5dd7c784121459e08ebd1ccb1a00
CPG 记录/材料包 ID：reference.doc.egg-lp
所属原叶：O04.L08
资格范围：静态参考材料。工具功能、官方 Benchmark、Dataset、OCI、硬件执行均未授予资格。

锁定 egg 0.11.0 的 LpExtractor、LpCostFunction、ILP 约束、共享 DAG 示例和求解器边界，供算法实现与审查时精确查阅。

本包不构建 egg，不安装 CBC/HiGHS/good_lp，也不运行求解器。0.11.0 文档中的 Cargo 示例仍写 0.10，原文保留；如实施应按锁定版本另行审查。超时或 gap 限制下的可行解不等于全局最优；最优性仅针对给定 e-graph、节点成本和实际 ILP 模型。

使用方式
1. 打开 readers/index.html，可在完全离线条件下定位章节和源码行；全部正文为本地文件。
2. python3 -B tools/reference.py verify
3. python3 -B tools/reference.py list
4. python3 -B tools/reference.py search 'T-depth'（查询词可改为 DAG、sketch、cost 等）
5. python3 -B tools/reference.py show <索引ID>
Python API：以 importlib 加载 tools/reference.py，调用 search(root, query)、show(root, entry_id)、verify(root)。

provenance
source/ 为压缩包内文件逐字节展开，原压缩包和来源证据保存在 upstream/。
source-lock.json 固定每个下载对象；expansion-manifest.json 将归档成员绑定到展开文件。
file-manifest.json 校验材料全部文件；reference-index.json 绑定文件哈希、行范围和原文片段哈希。
安装和查询均不执行上游软件，也不会联网获取依赖。需要运行工具时应使用负责该工具的 worker 提供的独立包与验收。
