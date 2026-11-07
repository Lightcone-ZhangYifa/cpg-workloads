Tree-sitter / C、C++、Rust grammar：worker001 已执行交付

任务身份
  review.engineering.tree-sitter
  review.engineering.tree-sitter-grammars
  plan_id = cpg-resource-research-20261101-v1
  新资源身份建议：tree-sitter、tree-sitter-grammars。
  原1862资源目录和资格未修改；不是新增Dataset或官方benchmark资格。

实际能力
  原生C运行时提供C/C++/Rust语法树，Python api.Parser提供parse、edit、snapshot。
  edit采用UTF-8字节offset，列号同样以字节计数；拒绝切入多字节字符内部的修改。
  snapshot保留每个节点的父节点、字段、类型、named/missing/error标记和字节/行列范围。
  节点以前序显式栈遍历，合法深层语法树不依赖Python调用栈深度。
  本接口不进行符号解析、类型检查或语义正确性证明。一个Parser实例不跨线程共享。

精确版本
  Tree-sitter运行时和官方CLI 0.26.10：3fc4cd21bca378f8acf8c823809de4706b1808f6
  tree-sitter-c 0.24.1：7fa1be1b694b6e763686793d97da01f36a0e5c12
  tree-sitter-cpp 0.23.4：f41e1a044c8a84ea9fa8577fdd2eab92ec96de02
  tree-sitter-rust 0.24.0：18b0515fca567f5a10aee9978c6d2640e878671a
  C++查询依赖tree-sitter-c 0.23.1：f4c21152f1952a99f4744e8c41d3ffb8038ae78c
  最后一项来自C++该commit的package-lock.json，不替换主C语法，也不单独计资源。
  source-lock.json包含全部官方下载URL、SHA256、字节数、许可证及依赖关系。
  C++依赖另外核对了上游package-lock中的SHA512完整性值。
  这是明确选择并验证的一组固定版本，不表示所有项目的最新版本。

准备、构建、验收
  raw/ 已附上全部6份不可变输入，当前离线重放不需联网。
  tools/prepare.py 是唯一提供下载的可选准备命令；下载仅接受现有锁定SHA。
  tools/build.py 不导入网络代码、不调用包管理器，按锁校验raw再展开到sources/。
  source、build和install目录必须互不嵌套；可显式改变三个目录。
  C运行时和三个语法parser.c/scanner.c已通过本机C编译器构建。
  CLI采用官方Linux x86_64预编译文件，未声明本地编译过Rust CLI。
  使用上游已生成parser.c，不运行grammar.js，不需要npm install或Node运行时。

  python3 tools/build.py
  python3 -B verify.py --scope all

  build.py可接收 --source-dir、--build-dir、--prefix、--evidence-dir 和 --cc。
  verify.py可接收 --scope runtime|corpus|all、--runtime-prefix、--grammars-prefix、
  --source-dir、--work-dir、--evidence-dir。所有校验输出与CLI缓存都写入work/evidence目录。
  验收拒绝work/evidence与源材料或安装prefix重叠，防止复制自递归或写入安装包；
  验收也拒绝python -O/PYTHONOPTIMIZE，防止禁用assert后形成虚假通过。
  corpus从源材料复制到工作目录后执行，没有使用--update，也没有排除任何用例。

Python使用
  from api import Parser
  with Parser("c", runtime_prefix=".../runtime", grammars_prefix=".../grammars") as parser:
      before = parser.parse("int f(void) { return 1; }\n")
      after = parser.edit(21, 22, "123")
  使用者按自身源文本计算字节位置；返回值是可序列化的字典。

独立prefix集成约定
  本次CPG集成采用无依赖环划分：tree-sitter包携带C runtime、CLI以及三语言已编译
  shared libraries作为配对运行闭包；tree-sitter-grammars包携带原源码/corpus及
  C++精确查询依赖，显式依赖tree-sitter。
  因而验收时 --runtime-prefix 与 --grammars-prefix 均指向tree-sitter运行包prefix，
  --source-dir 指向tree-sitter-grammars包的四目录源材料根。
  api.py也支持将runtime与三个language shared libraries放在不同prefix：前者含
  lib/libtree-sitter.so、bin/tree-sitter、include/tree_sitter/api.h；后者含
  lib/libtree-sitter-c.so、lib/libtree-sitter-cpp.so、lib/libtree-sitter-rust.so。
  校验脚本api.py与verify.py必须放在同一目录，使用python3 -B避免Python缓存。
  corpus --source-dir 目录包含tree-sitter-c、tree-sitter-cpp、tree-sitter-rust、
  tree-sitter-c-cpp-base四个已展开目录。各目录保留其test/、queries/、src/、
  tree-sitter.json/package.json与许可证。原始锁定archive另存，便于重建。
  runtime功能profile使用其配对grammar闭包完成有界验收；corpus任务不反向被依赖。

真实证据
  evidence/build-result.json：四个原生共享库的构建命令、退出码、平台及输出SHA。
  evidence/runtime-result.json：29/29通过，0失败0跳过。
  evidence/runtime-snapshots.json：全部测试源程序、完整节点树与范围。
  evidence/corpus-result.json：411/411上游parse corpus通过，0失败0跳过。
    C：85/85（8个corpus文件）；C++：179/179（16个）；Rust：147/147（8个）。
  evidence/*-corpus.stdout.json：CLI原始结构化输出，保留每个测试名称与结果。
  evidence/upstream-corpus-files.json：原corpus的逐文件SHA，运行前后完全一致。
  另有C的2个、C++的2个上游highlight fixture通过，不混入411个parse用例计数。
  runtime测试含正例、精确identifier范围、变长替换、多字节替换、多行插删、
  语法不完整及修复、非法UTF-8边界拒绝；所有增量树与fresh parse逐节点一致。
  新增1500层合法C括号表达式及变长编辑回归，核对每个节点、parent和field，
  修复原snapshot递归遍历在native parse成功后仍可能触发RecursionError的问题；
  Python默认递归上限没有提高。该修复未更改grammar，既有411项corpus结果保留。
  CLI结果按其官方枚举统计：Skipped与Platform均记跳过，Failed、Updated及未知
  outcome记失败；tools/check_outcome_classification.py保留该计数回归，独立于
  runtime和官方corpus数量。evidence/outcome-classification-review.json记录结果。
  时长和CLI输出的parse_rate仅保留原始日志，不作为正式性能benchmark成绩。

许可证和边界
  上游运行时与三个grammar主许可证均为MIT，原LICENSE及源码内附属许可证保留。
  Tree-sitter Unicode附属许可独立保存在install/licenses与原源码中。
  native共享库是当前Linux x86_64主机产物；其他平台应从已附源重建。
  官方CLI包仅提供Linux x86_64；其他CLI平台不在本轮功能资格内。
  结果只覆盖固定三语言上游corpus及上述增量接口，不声明整个语言规范或
  所有Tree-sitter grammar、Wasm、Windows、macOS、grammar再生成均已验证。

主要官方依据
  https://tree-sitter.github.io/tree-sitter/using-parsers/3-advanced-parsing.html
  https://tree-sitter.github.io/tree-sitter/cli/test.html
  https://github.com/tree-sitter/tree-sitter/releases
  https://github.com/tree-sitter/tree-sitter-c/releases
  https://github.com/tree-sitter/tree-sitter-cpp/releases
  https://github.com/tree-sitter/tree-sitter-rust/releases
  具体来源与commit以source-lock.json为准。浏览网页用于核实接口与项目身份，
  不将网页搜索摘要当作运行结果。
