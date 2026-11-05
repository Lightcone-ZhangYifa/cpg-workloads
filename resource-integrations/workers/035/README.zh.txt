CPG worker 035：既有测量工具复用与结果适配
计划：cpg-resource-research-20261101-v1
基线：compiler-playground 0.21.14
正式输出：cpg-20261101-worker-035-delta-v001.zip

一、完成范围

原分工的五条“复用已有能力，明确版本和接口边界”任务全部完成。
本增量不安装、升级或重新认证原工具，不新增资源 ID，不改变原目录及正式资格。

资源             原版本                                      原正式状态       本次处理
py.asv           0.6.6                                       F                保留；原定义核对、ASV v2 结果适配
google-benchmark v1.10.0 / a6b4a9f00b36c19af9997d68a1cf6e0b5b3d032c F             保留；重复样本、单位和 liveness 示例
apt.hyperfine    1.18.0-2build1                               trusted APT      保留；原始 times/exit_codes 严格适配
py.pyperf        2.10.0                                      F                保留；校准、warmup、测量值分离
apt.time         1.9-0.2build1                                trusted APT      保留；独立 TSV、退出码与计量精度处理

三个 F 来自正式历史覆盖集合，不代表当前宿主重新执行成功；两个可信 APT 没有被改成 F。
基线 Google Benchmark 的 current_host_system_blocked_inherited 记录保留。
全部原 id/version/sources/target/dependencies/provider/metadata.catalog/catalog_sha256
随五份原定义保留。新增测量/参考文件摘要另记，没有回填或覆盖原始锁。

二、真实执行了什么

1. 用原 0.21.14 的 PackageManager.info()/paths() 查询五项资源。
   全部完整定义与原支持目录一致；五个 metadata.catalog_sha256 与研究基线一致。
   查询使用显式独立 state/prefix/cache 路径，未创建安装 state 或 prefix，未调用安装。
   apt.hyperfine 和 apt.time 的真实 dpkg-query 结果为 absent。
   asv/pyperf 在此次执行所用的默认 Python 中不存在；这不是扫描全部既有环境的结论。
   空独立 state 中没有三个非 APT 的安装收据，因此不存在可声称“本机已恢复”的前缀。

2. 将研究基线的五项 managed/F/M/trusted 状态逐个与正式 coverage.json 的 id_sets
   比较；完全相符。精确源文件摘要和原 Library ID 在 qualification-inheritance.json。

3. 执行了 39 个具有失败判定的适配与集成测试，含 Python -O 复跑。
   覆盖错误退出、超时、错误正确性摘要、ASV 版本/参数变化、缺失原始样本、跳过结果、
   重复 JSON 键、NaN、错误单位、聚合冒充原样本、pyperf 双重除循环次数等风险。

4. 执行了真实 Python 命令的六个随机平衡配对区组，共 12 次计时调用，另有 preflight
   和 warmup。每次调用验证 sum(i*i for i in range(120000)) 的预声明精确输出摘要。
   保存每次 argv、exit code、stdout/stderr、内容摘要、计时、区组/先后顺序与前后宿主状态。
   另外真实执行错误输出、超时和退出父进程遗留后台后代三个负例，均拒绝，失败报告及原始输出保留。

第四项是适配层调度/正确性演示，计时覆盖整个进程；它没有运行上述五种工具。
共享宿主存在其他工作，演示没有产生正式编译优化、工具性能或“加速有效”的结论。
没有把合成格式 fixture 当成上游实测输出。没有执行 Google Benchmark C++、ASV 或
pyperf 的应用示例，因为对应原安装前缀没有恢复；示例是明确标注的复用入口。

三、为什么采用这些接口边界

ASV 0.6.6：只接收结果 schema 2；按 result_columns 映射，允许上游省略尾部空列。
必须同时提供 benchmarks.json，核对 benchmark version、时间类型、seconds 单位及参数
笛卡尔积顺序；只把 samples 纳入统计。summary-only、null/NaN、track 数值、变更后的
版本/参数不能混入计时。环境名、项目提交和 requirements 留在标准化记录中。
track_checksum 示例可作检查，但不能将它的整数返回值当时间。

Google Benchmark：real_time/cpu_time 已按迭代归一，不能再次除 iterations。
接受 ns/us/ms/s，显式换算为秒；保留 CPU 时间和迭代数。只接受 iteration 行，aggregate
行不充当额外观测；aggregate-only、错误、skip、零 iterations 或未知单位拒绝。
BM_Empty 与 BM_Sum(1/32/1024) 用于检查框架开销及执行活性；不自动扣除空测量，也不把
DoNotOptimize 当语义正确性的替代物。fixture 在计时前和计时后均验证 checksum。
构建已有库时不得临时联网取 GoogleTest；原定义已保留 BENCHMARK_DOWNLOAD_DEPENDENCIES=OFF。
本次没有建立另一套 Google Benchmark 构建或安装流程。

hyperfine 1.18：使用 times 原样本，单位始终为秒。每个样本必须有对应且为零的 exit_codes。
--ignore-failure 的非零结果拒绝。shell 校准产生零/负时间时不计算比值，应延长任务再测。
工具内重复次数不替代跨候选、随机先后顺序的配对区组。

pyperf 2.10.0：接收 JSON 1.0，合并 suite/benchmark/run 三级 metadata；warmups 原样
保留但不计入样本，calibrate/recalibrate runs 排除。values 已按 loops/inner_loops
归一，适配层不再做第二次除法。byte/integer 单位和纯校准结果不会被当作秒。

GNU time 1.9：使用独立文件与固定 LC_ALL=C，格式为
CPG_TIME_V1\t%e\t%U\t%S\t%M\t%x
区分 wall/user/system seconds 与 max RSS KiB；非零退出拒绝。同一文件多条记录拒绝。
输出为 0.00 时记录“低于报告分辨率”，不能据此产生零耗时或无限加速结论。
time 是进程用量计数工具；系统采样分析仍只使用项目约定的 perf。本增量未启动任何 profiler。

格式解析仅验证可消费的样本结构，不认证输入文件是谁生成、程序是否语义正确、资源已安装
或工具原始字节可信。正式实验应先由 CPG 原包接口核对安装身份，再执行受控程序/结果 oracle。

四、独立复跑

Python 3.10 或更新版本即可重放适配层验证，无第三方依赖、网络、下载、安装或管理员权限：

  python3 validate.py --output /absolute/new/worker035-validation

预期 validation.json：tests=39、actual_paired_blocks=6、actual_timed_invocations=12、
actual_failed_output_rejected=true、actual_timeout_rejected=true、actual_background_descendant_rejected_and_cleaned=true；upstream_tool_executions=0、
upstream_tools_installed=0、formal_qualification_changes=0。输出目录必须不存在。

在已安装正式 CPG 0.21.14 的 Python 环境中重放原定义/观察审计：

  python3 audit_existing.py --output /absolute/new/api-audit.json \
    --state /absolute/cpg/state --prefix-root /absolute/cpg/packages \
    --cache /absolute/cpg/download-cache

这里 state 应指向希望观察的既有 CPG 环境；未恢复 state 时查询不会发明安装路径。
它不执行 install/remove/check、不创建资源前缀。若定义或 catalog 摘要与此次基线不同，
直接失败，要求先审阅变更；不会自动接受一个同名新版本。

标准化已有工具输出：

  python3 src/measurement_reuse.py normalize google-benchmark results.json
  python3 src/measurement_reuse.py normalize apt.hyperfine results.json
  python3 src/measurement_reuse.py normalize py.pyperf results.json
  python3 src/measurement_reuse.py normalize py.asv result.json --catalog benchmarks.json
  python3 src/measurement_reuse.py normalize apt.time process-time.tsv

Python API 同时提供 parse_*、normalize、paired_plan、host_state 和 run_pairs。
run_pairs 只接受 argv 数组及绝对 executable 路径，不隐式执行 shell；每次结果都必须匹配
事先提供的 stdout SHA-256。进程失败、错误输出或超时立即阻断，已经产生的原始日志保留。
Linux 超时或发现后台后代会终止该调用拥有的进程组，处理进程恰好退出的竞态，并逐次记录清理确认。父进程成功但留下后台后代仍拒绝。本证明仅覆盖拥有的 Linux process group；另建 session 的脱离后代须由 CPG target 生命周期管理负责，本演示不替代正式测量的目标清理。原始计时没有被裁剪、择优、合成或静默剔除。

五、已有工具环境中的应用示例（本次未执行）

先从 PackageManager.paths() 取得真实原 prefix，不手写假设安装位置。

Google Benchmark：在独立 build 中将 examples/google_benchmark_fixture.cpp 与原
prefix/lib/libbenchmark.a 链接，保留编译器、flags、输入源码摘要。示例执行参数：

  ./fixture --benchmark_repetitions=5 --benchmark_min_time=0.05s \
    --benchmark_out=result.json --benchmark_out_format=json

pyperf：使用既有 py.pyperf 前缀中的 Python，不安装到当前默认 Python：

  /absolute/existing/prefix/bin/python examples/pyperf_fixture.py -o result.json

ASV：examples/asv 提供 local fixture。将 repo 配到实验的已有本地 Git 仓库，确保有
明确 commit；使用既有 Python 环境和 --record-samples，选择 time_sum 时间项。
不隐式创建新虚拟环境、下载依赖或把 track_checksum 混入时间统计。

hyperfine：保持明确 shell 策略，保存 warmup 和 command 原文，使用 --export-json；
不要启用 --ignore-failure，也不要将两个独立整组测量当成随机配对设计。

GNU time：用原工具路径、-o 独立文件、上述 -f 格式运行。短任务若输出 0.00，增加批量
或使用细粒度计时框架，不能修改报告值来制造非零结果。

六、文件与证据

worker-results.jsonl：原计划固定 17 字段、5 行、唯一 (plan_id,entity_kind,entity_id)。
assignment.jsonl：五条原分工，逐字段未改。
original-identities.json / original-definitions/：原 pin、SHA、许可和完整定义。
evidence/formal-api-replay.json：真实原 API 观察与完整定义比较。
evidence/qualification-inheritance.json：正式 F/M/managed/trusted 集合核对。
evidence/current-host.json：默认 Python/PATH 和实际宿主观察。
evidence/accepted-validation/：39 个测试、真实配对、错误输出、超时的原始证据。
source-reference/：固定版本官方文档/格式源码、许可证、下载摘要及失败记录。
SOURCE-NOTICE.txt：参考材料许可与范围。
src/、examples/、tests/、validate.py、audit_existing.py：可复用代码与入口。
summary.json：本 worker 的独立统计，新增资源/F/M/Dataset 均为 0。

参考来源优先原固定版本源码。GNU 在线手册已更新到 1.10，单列为补充；另从官方
time-1.9.tar.gz 提取了 1.9 原始 doc/time.texi，因此不会用新版网页代替原格式依据。
原 URL 失败的两个 404 被保留，正确路径的后续下载分别留有独立摘要。

本增量的价值是让既有工具输出能被 AI 实验程序可靠使用，同时保持原身份、失败信息、
测量层次和资格边界。它不改变工程版本、计数分母、Experiment/Trainer 或包管理器。

审查补充：原始结果和 ASV catalog 均只读取一次，解析与SHA-256绑定同一raw字节；catalog摘要随标准化记录保存。schema整数严格拒绝bool/float。evidence/final-validation为修正前34项检查的历史证据，evidence/accepted-validation为最终39项检查及进程清理负例，后者是当前验收依据。reviewed-validation和reviewed-validation-v2保留了开发时PID namespace/proc挂载不匹配触发的真实失败；最终实现使用当前PID namespace的killpg(pgid,0)核实进程组，不扫描或解释宿主/proc编号。
