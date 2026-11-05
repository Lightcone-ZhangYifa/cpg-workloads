# AMD μProf 5.3.521：官方材料与许可边界

## 工程用途
该材料帮助解释已有 perf 结果中与 AMD 微体系结构有关的问题。先区分定时采样、IBS、缓存事件与平台级指标，再回到对应处理器型号的公开事件定义；任何一种指标都不能仅凭同名字段跨型号比较。

## 固定身份与官方阅读入口
原工程固定 AMD μProf 5.3.521，保留原来源 URL、供应商 MD5、未知 SHA-256 和未知精确字节数。AMD 的产品页将 5.3.521 列为 5.3 更新构建；手册标识是 57368，版本 5.3。产品页给出 Linux、Windows、FreeBSD 的功能差异，系统分析和若干高级功能还受 EPYC 平台约束。这些是文档事实，不是本机功能证明。

- 产品及平台矩阵：https://www.amd.com/en/developer/uprof.html
- 5.3 用户指南：https://docs.amd.com/r/en-US/57368-uProf-user-guide/uProf-User-Guide
- 原版本授权入口：https://www.amd.com/en/developer/uprof/uprof-eula/uprof-5-3-eula.html?filename=AMDuProf_Linux_x64_5.3.521.tar.bz2

## 许可与交付范围
本次读取公开入口并记录响应字节的 SHA-256，未点击 Accept、未接受 EULA、未取得或复制安装介质。原页面正文未随包分发。LICENSES.txt 仅说明本包原创文字与产品权利的界限。原工具的完整材料资格不提升；公开产品页不能代替授权安装介质。

## 可复用的判断次序
先在现有实验记录中核对 CPU 型号、内核、perf 事件、采样周期、作用域和运行绑定，再查手册的相关指标解释。容器权限、驱动需求与硬件支持应另行记录。此包不尝试建立采集环境，也不提供可运行的采集命令。

## 本地使用
安装后在独立 prefix 中读取资料：

    python3 inspect_material.py --list
    python3 inspect_material.py --search metadata --limit 10

完整原归档位于 original-archives；source-lock.json 给出其身份，archive-members.json 给出每个原成员，reference-text.jsonl 是可检索的官方 UTF-8 文档视图。使用 --show 加完整 member 名称可读原始文本，不会执行其中的脚本。商业参考卡没有原始产品归档，使用 MATERIALS.md 和 source-lock.json 阅读其边界。所有程序调用均为本包自有静态阅读器；包内上游命令仅供阅读。
