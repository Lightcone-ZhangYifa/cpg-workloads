# Intel PCM 202604：PMU 语义和完整子模块材料

## 工程用途
该材料用于核对 core、uncore、内存控制器与平台遥测的定义。共享 socket 的 uncore 计数不能直接解释成某个线程或 cpuset 的独占成本；事件编码、单位、计数宽度和硬件代际也应逐项核对。本包不访问 MSR、PCI、PMU 或驱动，不编译或运行 pcm 系列程序。

## 完整来源闭包
主项目沿用原提交 abb6bce87cc2ed23d6677541ebcfc47ca769d1ed，版本 202604。五个原子模块是 Intel-PMT、perfmon、pugixml、simdjson、googletest。所有六个原归档的字节数和 SHA-256 均与原 CPG 锁一致；各自原许可和源目录挂载位置保存在 source-lock.json。完整 archive-members.json 可查询六个归档的全部成员，不会把只有父仓库的快照误算成完整材料。

## 阅读入口
src/cpucounters.h 提供公共类型与指标接口；主 README 和 doc 目录描述平台与功能边界；perfmon 子模块含事件定义，Intel-PMT 子模块含遥测材料。.gitmodules 和锁文件用于确认依赖身份，不能以当前上游分支替换原提交。pugixml、simdjson、googletest 是原依赖闭包的一部分，不计新增独立资源。

## 集成边界
原 intel-pcm 的 provider、来源、原版本、dependencies、target、catalog 保持不变。可安装文件是 intel-pcm 技术材料子包，其无编译或采集依赖。完整源码材料不等于已完成源码构建或 PMU 功能验证；本次新增 F 为零。

## 本地使用
安装后在独立 prefix 中读取资料：

    python3 inspect_material.py --list
    python3 inspect_material.py --search metadata --limit 10

完整原归档位于 original-archives；source-lock.json 给出其身份，archive-members.json 给出每个原成员，reference-text.jsonl 是可检索的官方 UTF-8 文档视图。使用 --show 加完整 member 名称可读原始文本，不会执行其中的脚本。商业参考卡没有原始产品归档，使用 MATERIALS.md 和 source-lock.json 阅读其边界。所有程序调用均为本包自有静态阅读器；包内上游命令仅供阅读。
