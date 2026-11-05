# 编译器开发中的构建与版本控制工具

以下五项沿用仓库中既有的冻结 APT 定义和已发布 wrapper。该接口说明没有重新安装或执行这些工具，也没有增加资源身份、F/M 或 benchmark 资格。完整包版本与来源以各自的 packages/<id>/package.json 为准。

## 版本和接口边界

| 原资源 ID | 冻结的包版本 | 在编译器开发中的接口 | 本轮明确的使用边界 |
|---|---|---|---|
| apt.cmake | 3.28.3-1build7 | `cmake -S src -B build -G Ninja`；`cmake --build build`；`ctest --test-dir build --output-on-failure` | CMake 配置与构建工具、CTest 测试调度分开。成功 configure/build 不表示测试已运行；测试须由项目 `enable_testing()` / `add_test()` 声明。编译器、flags、toolchain file 和生成器也要记录。 |
| apt.git | 1:2.43.0-1ubuntu7.4 | `git rev-parse HEAD`、`git status --porcelain=v1`、`git diff --binary`、`git worktree`；研究工作可用 commit 记录 checkpoint | 包版本包含 Debian/Ubuntu epoch `1:`，不得用 `git --version` 中的 `2.43.0` 取代完整包身份。commit 只固定已提交内容，未提交 diff、子模块、LFS 和工具链输入仍需另锁。 |
| apt.graphviz | 2.42.2-9ubuntu0.1 | `dot -Tsvg graph.dot -o graph.svg`；CMake 可产生目标依赖 DOT | 适合显示 CFG、依赖图等明确关系。Graphviz 排版不是程序分析，也不证明依赖完整或语义正确。输出布局与字体、插件相关，不应把图像逐字一致作为编译器正确性判定。当前在线文档中的新版本开关不能直接套到 2.42.2。 |
| apt.meson | 1.3.2-1ubuntu1 | `meson setup build src --backend=ninja`、`meson compile -C build`、`meson test -C build --print-errorlogs` | setup、compile、test 是不同阶段。声明清楚 native/cross file、编译器与选项；不复用不同配置的 build tree。`--wrap-mode=nodownload` 可用于要求构建不临时联网获取子项目的场景，所需子项目须提前准备。 |
| apt.ninja-build | 1.11.1-2 | `ninja -C build`、`ninja -C build -t commands`、`ninja -C build -t graph` | Ninja 执行生成的构建图，依赖关系来自上层生成器或 build.ninja。`-t graph` 是构建边图；生成成功或增量构建无工作不能证明测试执行。`compile_commands.json` 的生成需由 CMake/Meson 等明确启用或提供。 |

上表是使用契约与示例，**不是声称本次已在冻结闭包中执行这些命令的日志**。

## 用于回归任务的组合顺序

1. 在任务专用 worktree 中固定编译器源码 commit，记录 dirty diff、子模块及输入摘要。
2. 选择一种构建入口：CMake 生成 Ninja，或 Meson 生成 Ninja。source、build、install prefix 与 Environment 分开。
3. 构建完成后显式运行项目测试；同时保存退出码、被选择的测试清单、实际结果与未执行项。DejaGNU、CTest、Meson test 的通过规则各按其原生语义处理。
4. 需要分析关系时，用 CMake/Ninja 输出的 DOT 喂给 Graphviz。图中的节点/边仍以构建系统或编译器导出的关系为准。
5. 将真实工具版本、配置、环境和输出纳入实验记录；系统性能分析沿用 perf。

这些步骤不修改既有 Experiment/Trainer，也不创建新的训练器或控制器抽象。

## 包身份和依赖

每个资源的完整冻结 sources 与依赖闭包入口均保存在其原始 `package.json`；本次静态复用说明见 `catalog/resources/dejagnu-source/static-review.json`。APT 原许可证标识保留 `LicenseRef-Ubuntu-main-or-universe-package-notices`，部署时保留原 `/usr/share/doc/<package>` 通知及相关源码义务，不能把五个包统一标成一个宽泛许可。

这里沿用五项 `managed=true, trusted_apt=true`。原表 `material=false, functional=false` 保持不变；trusted APT 资格与 F/M 统计分别计算，不能将“复用完成”写成新增五项 F 或 M。

## 官方接口参考

- CMake 3.28 命令手册：<https://cmake.org/cmake/help/v3.28/manual/cmake.1.html>
- CMake 3.28 `add_test`：<https://cmake.org/cmake/help/v3.28/command/add_test.html>
- Git 2.43.0 命令手册：<https://git-scm.com/docs/git/2.43.0>
- Meson 1.3 发布说明：<https://mesonbuild.com/Release-notes-for-1-3-0.html>
- Meson 命令行参考：<https://mesonbuild.com/Commands.html>（在线文档会随版本更新，使用冻结版本支持的选项）
- Ninja 1.11.1 源码内手册：<https://github.com/ninja-build/ninja/blob/v1.11.1/doc/manual.asciidoc>
- Graphviz 命令行：<https://graphviz.org/doc/info/command.html>（例如 `-A` 的文档明确要求 ≥13.1.0，不属于此冻结包）

本次整理没有下载这些 APT 包，也没有运行其安装 hook。
