# Scalasca Trace Tools 2.6.2：并行 trace 语义与格式

## 工程用途
该材料面向 MPI 等待、同步关系和并行 trace 分析的实现研究。一次调用的持续时间、其中的等待时间与全局 critical path 是不同量；要解释某段等待，需要同时核对通信事件、调用上下文和进程关系，不能只依据局部时间长度下结论。

## 固定发行与格式入口
Scalasca 2.6.2 官方发行的 SHA-256 为 17e72fd908be43879955e4ed49c2732d4dbda7d295fec2d8b3af7ddafe1202a0，原 MD5 为 8628cb026e1a9bd6399087c7eea93106。发布者资料确认其与 Score-P 9.0、OTF2 3.1、Cube 4.9 的兼容关系。
原发行内包含 vendor/otf2、vendor/cubew、用户指南和许可证。OTF2 表达事件 trace，CUBE4 用于 profile；这些格式的角色不能互换。格式与 reader 接口可直接由本包阅读器定位，PDF 用户指南保留在完整归档内。

## 来源与许可
- 官方发行：https://apps.fz-juelich.de/scalasca/releases/scalasca/2.6/dist/scalasca-2.6.2.tar.gz
- 发布者归档：https://zenodo.org/records/15125898
- 官方许可入口：https://www.scalasca.org/scalasca/software/scalasca-2.x/license.html

## 验证范围
本包已验证完整原始发行与可检索材料，未执行 Score-P、scalasca、trace analyzer、MPI 或任何采集入口。发行内 vendor 内容保持原样；运行时的 MPI、Score-P 或系统库不因此被认证。源码构建、真实 trace 分析、性能收益和官方 Benchmark 均未在本轮验证。

## 本地使用
安装后在独立 prefix 中读取资料：

    python3 inspect_material.py --list
    python3 inspect_material.py --search metadata --limit 10

完整原归档位于 original-archives；source-lock.json 给出其身份，archive-members.json 给出每个原成员，reference-text.jsonl 是可检索的官方 UTF-8 文档视图。使用 --show 加完整 member 名称可读原始文本，不会执行其中的脚本。商业参考卡没有原始产品归档，使用 MATERIALS.md 和 source-lock.json 阅读其边界。所有程序调用均为本包自有静态阅读器；包内上游命令仅供阅读。
