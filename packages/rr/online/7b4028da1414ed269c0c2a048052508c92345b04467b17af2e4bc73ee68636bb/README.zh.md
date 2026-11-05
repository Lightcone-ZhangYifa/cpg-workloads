# rr 原始预编译发布包的在线配方

固定资源 ID 为 `rr`，原始 provider 为 `material`，原始版本为 `5.10.0`，原始目标记录为 Ubuntu 24.04/x86_64，不能以其他发布版本、HEAD 或省略文件替换。

原始来源 URL：`https://github.com/rr-debugger/rr/releases/download/5.10.0/rr-5.10.0-Linux-x86_64.deb`

原始归档 SHA-256：`fe3ccb579eab96220b2b91b918ce80da7173f3c098804370a93247a056fab3a1`；原始长度：`2974106` 字节。

在线获取：`python3 acquire.py --output ./rr-5.10.0-Linux-x86_64.deb`。完整 HTTPS 获取后逐块检查严格原始长度和 SHA，拒绝内容不符、超长与覆盖既有路径。本轮本地 loopback HTTP 服务器验证了完整传输和截断、变造、过长三种失败路径；**没有向 GitHub 实际下载，不能声称在线远端连通性已验证**。

离线部署：将同时交付的 `rr-5.10.0.material.cpgpkg.tar.gz` 交给 `PackageManager.install`，得到独立前缀下 `payloads/rr` 原始 `.deb` 文件。此操作不会调用 APT、不会更改宿主 dpkg 数据库。需要执行二进制时，由开发者明确在隔离环境中将该 `.deb` 解包到自己的测试前缀，再检查 ELF 运行库。

实际检查范围：该原始 DEB 控制字段 `Package=rr`、`Version=5.10.0`、`Architecture=amd64`，具备真实 `rr` ELF 和 preload/runtime 文件。两个独立 material 前缀安装成功；在独立临时提取目录中实际执行 `rr --version` 返回 `5.10.0`。但实际 record/replay 需要 CPU PMU、内核 ptrace 和容器权限；本次 `rr record` 探测未通过，**不计为 rr 功能、硬件或 OCI 合格**。原始包声明的 5 个 APT 依赖以及原始功能检查保留在 CPG metadata 的 `static_only_profile`，静态 material 复制不查询/安装这些依赖；执行版必须按原始依赖契约验证。
