# Caliper 2.15.0：标注接口、metadata 与数据格式

## 工程用途
Caliper 把程序区域标注、上下文 metadata 和可配置分析记录组织到同一接口体系。对编译器 Agent 的价值在于理解源码区域如何对应记录中的属性和层次，以及导入既有结果时如何保留上下文。本包仅提供源码和格式材料，不构建或加载 instrumentation library。

## 固定来源
官方 v2.15.0 标签解析为 c4efbd8b15186cb9854bbd57b99c569dd91867f8。完整原归档、上游 BSD-3-Clause 许可、公共头文件、Sphinx 文档和 Python reader 源码均在包内；原归档未经修改。官方入口：https://github.com/LLNL/Caliper/releases/tag/v2.15.0 。

## 阅读顺序
先读 AnnotationAPI.rst，再读 ConfigManagerAPI.rst 和 OutputFormats.rst；随后核对 include/caliper/reader 中的接口及 python/caliper-reader。标注名、属性类型、配置名称与记录中的字段是不同层次，不能仅用一个区域名称断言数据可跨运行合并。
.cali 记录、JSON 导出及 CalQL 查询接口都保留官方文档与实现。离线阅读器只检索这些材料，不调用 cali-query，也不采集新记录。

## 完整性边界
M 依据完整固定源码归档与文档；本次未验证源码构建、运行库依赖、采样、GPU 活动、MPI 或官方 Benchmark。资料内涉及其他分析器的说明保留为参考，并不授权本项目启用这些采集路径。

## 本地使用
安装后在独立 prefix 中读取资料：

    python3 inspect_material.py --list
    python3 inspect_material.py --search metadata --limit 10

完整原归档位于 original-archives；source-lock.json 给出其身份，archive-members.json 给出每个原成员，reference-text.jsonl 是可检索的官方 UTF-8 文档视图。使用 --show 加完整 member 名称可读原始文本，不会执行其中的脚本。商业参考卡没有原始产品归档，使用 MATERIALS.md 和 source-lock.json 阅读其边界。所有程序调用均为本包自有静态阅读器；包内上游命令仅供阅读。
