# bril · worker 007

固定官方解释器与上游TDCE；算术/分支/循环3程序、12输入逐项对照，并检查2个非法程序及输出变异体。仅适用于本组有界Core程序，不把教学TDCE当通用等价证明。Deno为上游原生预编译运行时，Bril解释器源码保持原样。

## 离线安装与验收

```bash
python3 recipe/install.py --prefix /absolute/empty/prefix --jobs 2
python3 recipe/check.py --prefix /absolute/empty/prefix --out /absolute/evidence
```

安装目录必须为空。`--build-root`只选择独立临时build的父目录；输入源码另保留在安装目录的`share/cpg/source/`，不会在源码中构建。安装、检查、在线准备是三个独立动作。每次安装前核对全部原始资产字节数及SHA-256。系统工具要求见`source-lock.json`，没有发行版硬编码。

需要重新获取原始输入时，显式运行`python3 recipe/prepare.py --destination /absolute/asset-root`，之后安装可传`--assets-root /absolute/asset-root`。安装阶段不访问网络。

使用入口位于`prefix/bin/`；`prefix/bin/cpg-check --out /absolute/evidence`可重放任务验收。源码、原始许可证、测试样例及失败边界均随包提供。来源锁与每资源证据是本交付的权威事实；不修改旧1862项目资格或正式版本。
