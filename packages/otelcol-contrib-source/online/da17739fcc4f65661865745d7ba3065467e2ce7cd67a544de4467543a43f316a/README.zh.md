# OpenTelemetry Collector Contrib 0.163.0 固定源包材料

原始 ID：`otelcol-contrib-source`；原始 provider `material`；原始目标为 Linux x86_64 / Ubuntu 24.04（仅参考目标，不是发行版硬拦截）。

唯一允许的原始来源 URL：`https://github.com/open-telemetry/opentelemetry-collector-contrib/archive/refs/tags/v0.163.0.tar.gz`；原始 SHA-256：`a9277bf9d19f9359a4a6f262e9c6cd98524bd6f2442950a8dce615fbe062f98e`；准确体积 `16944016` bytes。不能替代为 HEAD、其他 tag 或下载片段。

执行 `python3 acquire.py --output ./otelcol-contrib-0.163.0.tar.gz` 从原始 URL 获取，严格校验完整传输的 SHA-256/bytes，拒绝变更和覆盖文件。对应离线分发 `otelcol-contrib-source-0.163.0.material.cpgpkg.tar.gz` 可用 CPG `PackageManager.install()` 安装到全新前缀；原始压缩包位于 `<prefix>/sources/otelcol-contrib-0.163.0.tar.gz`。校验脚本核对所有 16,969 个归档条目、13,916 个普通源文件及 90,310,786 逻辑字节，确认无未审查链接或声明的 Git 子模块，并检查 LICENSE、go.mod 等标志文件。

本次执行对两个独立离线前缀进行了真实安装与内容验证，并用环回 HTTP 实测在线传输正例、截断、篡改和超长三个反例；**真实 GitHub 远程连接未被验证**。原始源码静态材料齐备不代表 Go modules、Go 构建、Collector 运行、OCI 运行或设备级采集完成；这些维度仍未合格，也不得冒充独立软件功能测试。
