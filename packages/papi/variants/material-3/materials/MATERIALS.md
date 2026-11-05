# PAPI 7.2.0：事件、组件和公共接口材料

## 工程用途
PAPI 的 preset 事件、平台 native 事件和 component 接口处在不同层次。阅读事件映射时应同时检查 CPU 选择、事件编码、派生表达式和组件能力；同一 preset 名称不保证各处理器的底层计数完全等价。component 文档也可帮助区分硬件、软件与第三方运行时事件来源。

## 固定来源
使用原 papi-7.2.0.tar.gz，SHA-256 a9bff89ccf39915d729e08ae0a0c6a71ce0ebbe98411e9a2eb3c83c8db0af39c，4,420,651 字节。原发行包含公共头文件、papi_events.csv、组件说明及随附 libpfm 资料；保留全部原许可证。官方发行入口：https://github.com/icl-utk-edu/papi/releases/tag/papi-7-2-0-t 。

## 离线阅读入口
src/papi.h 用于查找公共接口与错误值；src/papi_events.csv 用于核对事件映射；src/components/perf_event 和 src/components/sde 的说明分别提供硬件事件接入与软件事件设计线索。先确定所研究组件，再读其接口与权限限制，避免把整个 PAPI 当作单一硬件计数器。

## 资格与执行边界
PAPI 原 F=true 继承保留，本轮新增 F=0。没有调用 PAPI 初始化、组件探测、事件启动或计数器读取，也不以材料校验重新认证旧运行库。原资源依赖和来源字段保持不变；papi 仅安装静态参考。

## 本地使用
安装后在独立 prefix 中读取资料：

    python3 inspect_material.py --list
    python3 inspect_material.py --search metadata --limit 10

完整原归档位于 original-archives；source-lock.json 给出其身份，archive-members.json 给出每个原成员，reference-text.jsonl 是可检索的官方 UTF-8 文档视图。使用 --show 加完整 member 名称可读原始文本，不会执行其中的脚本。商业参考卡没有原始产品归档，使用 MATERIALS.md 和 source-lock.json 阅读其边界。所有程序调用均为本包自有静态阅读器；包内上游命令仅供阅读。
