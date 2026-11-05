# LIKWID 5.5.2：拓扑、事件组和 benchmark 资料

## 工程用途
拓扑、CPU 编号、线程绑定及事件组是解释性能实验环境的重要背景。先明确操作系统逻辑 CPU 编号与硬件线程/核心/socket 的对应，再判断某个事件组公式适用于哪一代 CPU。事件组中的原始计数器集合与派生指标公式应分别阅读，不能把公式名称等同于实际已测量数据。

## 固定来源与离线入口
原提交 22abb561ca709ea867562f3801dcaff676a30f1a、版本 5.5.2 的完整原归档与原 SHA-256 一致。doc/applications/likwid-topology.md、likwid-pin.md、likwid-perfctr.md、src/includes/perfgroup.h 和 groups 中的原始事件组均可离线检索。benchmark 内核源码也保留在完整原归档中，但本次不执行 benchmark 或测量。

## 资格与操作边界
原 LIKWID 已有 F=true，该历史事实保留；本次只增加固定材料证据，未重新运行任何 LIKWID API、拓扑命令或采集器。perfctr、频率调整、特性开关和访问守护进程均未启动。技术材料子包不修改原 likwid 包定义、原 build 或依赖。

## 本地使用
安装后在独立 prefix 中读取资料：

    python3 inspect_material.py --list
    python3 inspect_material.py --search metadata --limit 10

完整原归档位于 original-archives；source-lock.json 给出其身份，archive-members.json 给出每个原成员，reference-text.jsonl 是可检索的官方 UTF-8 文档视图。使用 --show 加完整 member 名称可读原始文本，不会执行其中的脚本。商业参考卡没有原始产品归档，使用 MATERIALS.md 和 source-lock.json 阅读其边界。所有程序调用均为本包自有静态阅读器；包内上游命令仅供阅读。
