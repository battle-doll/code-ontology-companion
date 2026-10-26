# 0.9.2 遗漏检测与覆盖率验证

[English](../COVERAGE_0_9_2.md) | [한국어](../ko/COVERAGE_0_9_2.md) | [日本語](../ja/COVERAGE_0_9_2.md) | [简体中文](COVERAGE_0_9_2.md) | [Русский](../ru/COVERAGE_0_9_2.md)

开发者：**battle-doll (배틀돌)**。AI 继续使用本地 MCP，人使用生成的离线 HTML。保留 Windows、macOS、Linux 支持；实际操作系统验证与本地回归测试分别报告。本流程不会发布、安装或重启目标应用。

## 先列出全部选定范围

可以要求 AI：“先列出我选择的全部范围，把排除和失败项留在分母中，再展示六个覆盖阶段及剩余缺口。”清单扫描为只读操作。

```sh
python3 "$COMPANION" coverage-inventory --repo /path/to/source --source-root src
```

默认清单使用 pipeline 适配器；`--mode legacy` 测量原有 Java/Python 支持。内置忽略目录仍保留在清单中。此清单不解析 `.gitignore` 模式，因此它不保证相关排除或完整性。

`COMPANION` 指受信任包内的 `skills/manage-code-ontology/scripts/companion.py`。使用已有的 Python 3.9 或更高版本；Windows 可用 `py -3`。多个授权根目录可重复传入 `--source-root`。验证输出存放在源码和安装目录之外。不能仅凭敏感样式的文件名静默丢弃正常源码结构。秘密值、链接或 reparse point、不安全路径及不可读内容仍受保护；排除项、不支持的语言、资源限制、编码错误和无法访问的边界均保留。目录无法读取时，全部文件的分母为 `UNKNOWN`。

无法处理的项目必须保留目标、原因、影响和替代方案，在越过该阻塞项之前取得用户决定；已授权的正常处理无需再次批准。

## 六项指标分别报告

| 阶段 | 可以计入的证据 | 不能证明完成的内容 |
| --- | --- | --- |
| `scope_files` | 独立选定的全部文件中已处理的文件 | 仅通过过滤器的文件 |
| `declarations_types` | 明确期待集合中的准确声明与类型 | 文件存在或名称相似 |
| `exact_calls` | 准确调用位置、目标声明及匹配证据 | 候选、placeholder、`IMPORTS`、`IMPLEMENTS`、运行时猜测 |
| `policy_semantics` | 独立对照已表达片段的必要条件和公式 | 存在策略节点或数值常量 |
| `mcp_delivery` | 一个固定查询的所有页面及准确预期 payload | 仅 `truncated=false` 或部分页面 |
| `policy_document` | 独立确认对应段落描述了原始语义要素 | 仅引用、哈希或未经审查的文本 |

每项保留分子、分母、比例、测量范围、遗漏、证据和限制。不知道分母时使用 `UNKNOWN`，不表示 0 或 100%。样本比例仅适用于该样本。部分描述单独统计，不赋予任意 0.5 分。已生成关系的证据附着率不是全部源码覆盖率。存在遗漏、不支持或未知项时，即使命令和 snapshot 生成成功，整体完整性仍为 `PARTIAL` 或 `BLOCKED`。

## 固定 snapshot 与语义来源

对 pipeline workspace，先通过 `ontology_pipeline_status` 取得具体 snapshot，再通过 `ontology_pipeline_coverage` 读取全部文件处理页面。`ontology_pipeline_search` 支持 `callsite` 和 `semantic_fragment`。准确静态调用、候选、未解析调用分别表示；静态接口目标不代表实际运行时实现。Java 片段保留受限字段、常量、赋值、条件和返回表达式结构。任意字符串及敏感值不保存；未解析调用、不支持的控制流和缺少初始化值均保留位置与原因。`represented` 仅表示支持的表达式语法已保留，不证明完整业务规则。缺少独立支持的绑定时，单位为 `UNKNOWN`。已有可执行 typed-policy 仍是单独契约。

结果绑定 `snapshotId`、`sourceFingerprint`、`scopeDigest`、`analysisSpecId`，源码位置绑定文件哈希。沿 `nextOffset` 读取至末页，保留 `queryDigest`、offset、total、returned 和 payload。首、中、末页缺失，混合 snapshot、哈希或查询，重复 ID 及同 ID 内容篡改都会使回执无效。读取已保存 snapshot 的状态不等于重新验证源码最新性。

`coverage_contract.validate_policy_document` 接收独立源码期待集合、片段、MCP 页面、文档字节和声明。单独输入的 `semantic_reviews` 绑定精确期待集合、源码证据、文档、段落、覆盖语义要素、审查者及 snapshot。哈希只证明一致性，语义是否成立仍须独立审查。直接阅读源码补充的描述标记为 `direct_source_supplemented`，即使描述完整也不计入 `ontologyOnlyFull`。完整、部分、未描述和无支持声明分别统计；源码、snapshot、期待集合或段落改变后必须重新验证。 每项声明必须将 `directSourceSupplemented` 明确设为 JSON 布尔值 `true` 或 `false`；缺失或其他类型会使知识依据保持未验证。

将已测量的六阶段指标输出到本地：

```sh
python3 "$COMPANION" coverage-validate --input /path/to/coverage-request.json --output /path/to/new-verification
```

输入包含 `binding`、六项 `metrics` 和 `remaining`。该命令检查指标一致性并生成 `coverage.json`、`coverage.md`；不会推测分母、代替独立段落审查或证明整体完整性。非公开源码及验证产物保留本地；公开 fixture 和报告不得包含个人信息、秘密值或运营内容。
