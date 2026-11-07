# libfirm · worker 007

固定与cparser配对的libFirm源码构建，手写SSA IR经graph verifier和x86-64后端输出汇编，再由系统工具链接运行6个输入；执行全部12个上游unit tests。仅为有界功能证据，不是所有后端/优化的正确性证明。

## 离线安装与验收

```bash
python3 recipe/install.py --prefix /absolute/empty/prefix --jobs 2
python3 recipe/check.py --prefix /absolute/empty/prefix --out /absolute/evidence
```

安装目录必须为空。`--build-root`只选择独立临时build的父目录；输入源码另保留在安装目录的`share/cpg/source/`，不会在源码中构建。安装、检查、在线准备是三个独立动作。每次安装前核对全部原始资产字节数及SHA-256。系统工具要求见`source-lock.json`，没有发行版硬编码。

需要重新获取原始输入时，显式运行`python3 recipe/prepare.py --destination /absolute/asset-root`，之后安装可传`--assets-root /absolute/asset-root`。安装阶段不访问网络。

使用入口位于`prefix/bin/`；`prefix/bin/cpg-check --out /absolute/evidence`可重放任务验收。源码、原始许可证、测试样例及失败边界均随包提供。来源锁与每资源证据是本交付的权威事实；不修改旧1862项目资格或正式版本。
