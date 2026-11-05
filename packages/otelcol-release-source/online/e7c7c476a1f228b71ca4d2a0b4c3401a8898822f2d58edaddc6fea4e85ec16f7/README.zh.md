# otelcol-release-source：原始锁定源码材料的在线配方

资源 ID：`otelcol-release-source`；原始版本：`0.163.1`；原始 provider：`material`；原始目标记录为 Linux x86_64 / Ubuntu 24.04。

原始来源 URL：
`https://github.com/open-telemetry/opentelemetry-collector-releases/archive/refs/tags/v0.163.1.tar.gz`

记录 SHA-256：`1fe4777ebd82f19498e41471b06e646708f5ae80c4380e136a4b06cfc15dc884`；完整源归档 **171270 字节**。版本/URL/目标字段均取自固定原目录，不使用 HEAD、替换 tag 或缩小文件集。

在线下载：`python3 acquire.py --output ./otelcol-releases-0.163.1.tar.gz`。脚本通过标准 HTTPS 获取完整数据，严格限制最大字节数、完成后核对原始 SHA-256 和字节数，使用独占输出路径，拒绝内容不符与覆盖已有文件。

离线部署：使用单独的 `otelcol-release-source-0.163.1.material.cpgpkg.tar.gz`，通过 `compiler_playground.packages.manager.PackageManager.install(archive, prefix=...)` 安装到全新独立前缀。随后可运行 `tools/check_material.py --prefix <前缀>` 检查归档内容和完整性。

验证范围：从已保存的历史源原料中按 SHA 精确复原了原始压缩包，检查它拥有 207 个原始条目、177 个普通文件，无子模块声明和异常链接；本轮经过两个彼此独立的 CPG 前缀完整安装与检查，以及一个独立前缀安装/卸载周期；另以本地 HTTP 测试服务器成功演练完整在线传输路径并验证不匹配的 3 个反例。本执行环境未直接向原始 Github URL 发起传输，**不声称完成真实远程下载**。静态材料可用不代表 Collector 编译完成，更不代表实际数据采集、OCI 或硬件执行通过。
