# Vampir：输入格式和授权边界参考

## 工程用途
Vampir 的交互视图可作为理解并行时间线和通信呈现方式的参考。本包只整理公开输入格式与授权入口，帮助 Agent 判断一份已存在的 trace 是否值得在获得许可后交给相应工具；不执行 Vampir 或新增采集。

## 官方资料摘要
官方入门页列出 OTF、OTF2 以及 ELG/ESD 等 trace 入口；打开输入文件与完成产品授权是不同步骤。许可页面分别说明个人许可和站点许可的适用范围，不能把公开 demo 入口视为任意再分发或通用使用授权。当前公开网站标识 10.9；此处版本仅标识 2026-11-02 的参考卡，不声称已取得 10.9 安装介质。

- 输入与首次使用：https://vampir.eu/tutorial/manual/getting_started
- 许可范围：https://vampir.eu/licensing
- 平台列表：https://vampir.eu/platforms
- 官方手册与示例入口：https://vampir.eu/downloads

## 交付与许可边界
本包包含原创中文说明、官方 URL 和取得页面时的内容指纹；网页、PDF 手册、商业安装程序、许可文件与官方 trace 示例均未复制到交付包中。没有发送申请、激活产品或接受厂商条款。工具完整 M 与 F 均未建立；此次完成的是任务表允许的静态参考与许可边界整理。

## 输入检查建议
研究既有 trace 时先核对格式版本、记录器、时钟来源、时间单位、MPI rank/线程映射及文件集合是否齐全。格式扩展名只用于识别入口，不能单独证明文件可读、时间同步正确或指标有效。

## 本地使用
安装后在独立 prefix 中读取资料：

    python3 inspect_material.py --list
    python3 inspect_material.py --search metadata --limit 10

完整原归档位于 original-archives；source-lock.json 给出其身份，archive-members.json 给出每个原成员，reference-text.jsonl 是可检索的官方 UTF-8 文档视图。使用 --show 加完整 member 名称可读原始文本，不会执行其中的脚本。商业参考卡没有原始产品归档，使用 MATERIALS.md 和 source-lock.json 阅读其边界。所有程序调用均为本包自有静态阅读器；包内上游命令仅供阅读。
