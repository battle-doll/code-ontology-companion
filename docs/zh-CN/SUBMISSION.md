# OpenAI 插件提交说明

[English](../../SUBMISSION.md) | [한국어](../ko/SUBMISSION.md) | [日本語](../ja/SUBMISSION.md) | [简体中文](SUBMISSION.md)

## 上架信息

- 名称：Code Ontology Companion
- 版本：0.5.0
- 开发者：battle-doll
- 类别：Developer Tools
- 分发：Public
- 提交类型：Skills only
- 组件：deterministic ontology skill 与 CLI、offline workbench、可选的基于同意的 Ollama helper，以及 local MCP setup workflow
- GitHub package：相同 skill 加上内置的跨平台 read-only stdio MCP server
- 许可证：Apache-2.0

简短描述：

> 无障碍离线 3D 代码图谱

详细描述：

> 把已获授权的 Java、Spring 或 Python repository 静态映射为具有 rule-attributed relation evidence 和明确 adapter coverage 的不可变本地 knowledge-graph snapshot。可通过默认 2D 或具备 keyboard/pointer、reduced-motion、high-contrast、assistive status 和安全 2D fallback 的可选 Canvas2D 3D 探索同一 bounded neighborhood。自包含 workbench 不使用 CDN、WebGL、worker、telemetry 或 network；deterministic analysis 不执行 target code。

## 访问与数据使用声明

| 领域 | 版本 0.5.0 行为 |
| --- | --- |
| 身份验证 | 无 |
| 直接 network access | Deterministic analyzer/workspace 无。明确同意后，可选 helper 只使用固定 `127.0.0.1:11434` |
| 外部 API | 仅可选的现有 local Ollama API；无 remote 或 publisher API |
| telemetry/analytics | 无 |
| target-code execution | 无 |
| 读取 | 明确 repository path 下已获授权的普通 `.java` 和 `.py` file |
| 排除 | 类似 secret 的 name、key、env file、link/reparse point、VCS、dependency、build output、cache、special 和 oversized file |
| 写入 | Repository 外的新 explicit workspace、不可变 refresh snapshot、append-only lineage；另行获得 local-LLM 同意后，写入 private workspace configuration 和 create-only inferred sidecar（POSIX mode `0600`；Windows inherited workspace ACL） |
| private local state | Absolute repository path、每个 file 的 relative path/size/SHA-256、workspace/snapshot/event ID、可选 Git revision；启用时还包括 local model name/digest/capability 和 normalized inferred suggestion |
| portable artifact | Symbol、legacy-compatible relation triple、stable rule ID、定性 evidence basis、runtime-status indicator、bounded limitation、relative path/可选 line span、adapter coverage、RDF/Turtle `RelationshipEvidence`、lineage、offline HTML |
| visualization | 默认 keyboard-accessible 2D 与显示相同 bounded neighborhood 的可选 Canvas2D 3D、明确 rendering budget、reduced-motion/high-contrast、assistive status、hidden-tab pause、2D failure fallback |
| 不保留 | Source body、comment、arbitrary string literal、policy value、credential、raw prompt、raw model response |
| upload | 无 |
| background service | 无；可选 watcher 仅为明确的 foreground-only 操作 |
| MCP | 可选 local stdio server，只读，不开放 listening port，只使用已注册 workspace ID；skill bundle 中记录 Windows、macOS 和 Linux setup |
| MCP write | 无 |
| hook/app/widget | 无 |
| package/model/database 安装 | 无 |
| 是否要求 local LLM | 不要求。Workspace 范围同意后，仅可选使用现有 Ollama，不 install/download，也不启动 Ollama service。Enrichment 每个 request 最多 20 个 candidate 和 16 KiB，使用 `think=false`、`num_ctx=8192`、`num_predict=2048`、最长 180 秒 timeout、atomic sidecar publication 和 `keep_alive=0` |

## 本地 MCP annotation

七个 MCP tool 都设置：

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

Tool 提供 workspace 列表、status、search、static neighbor、history、snapshot comparison 和 lineage。Initialization、refresh、lineage write、installation、deletion、upload、target execution 和 arbitrary path access 不通过 MCP 暴露。Windows、macOS、Linux 的完整 configuration 和验证流程见[只读本地 MCP 指南](references/local-mcp.md)。

## 审查依据

此 release 无需 cloud account、remote service、graph database 或 model，即可提供独立的 deterministic value。它要求：

1. repository authorization
2. no-write preflight
3. repository 外的 explicit workspace
4. initialization 前的 explicit authorization
5. 使用 static-evidence language，而不是 runtime 或 causal claim
6. 在任何可选 loopback model inspection 或 workspace configuration 前，进行独立 disclosure 并取得 consent

Analyzer 独立强制 authorization flag、output separation、link/reparse/special-file avoidance、sensitive-path exclusion、source-size limit、deterministic path 无 network access 以及禁止 target execution。Refresh 使用 stable manifest、staging、validation、不可变 snapshot 和 atomic promotion。Source 与 release-artifact validation 还会检查 supported component metadata、documentation、deterministic package content 和 extracted smoke behavior。

Executable golden/forbidden ontology quality gate 在不执行 target repository 的情况下检查 expected/prohibited node 与 relation、必需 evidence field、adapter coverage 和 deterministic output。定性 evidence basis 与 `runtime_unknown` 不是 opaque numeric confidence 或 runtime proof。本文档不声明任何特定 build 或 CI 已通过。

Visualization gate 检查 offline/self-contained 边界、2D default/3D opt-in、finite budget、keyboard/pointer 替代操作、reduced-motion/hidden-page、high-contrast/assistive marker、legacy payload 和 2D recovery。Canvas 3D 是辅助视图；DOM 搜索、关系列表、详情与 2D 是等效无障碍路径。以 WCAG 2.2 AA 为设计目标，但在没有单独手动 AT/browser 验证时不作全面合规声明。

可选 local enrichment 不属于 observed analyzer authority。Indicator check 不执行程序，也不建立连接。取得同意后，helper 仅使用 literal IPv4 loopback，拒绝报告的 cloud/remote marker、缺失或无效的必要 API metadata 以及 unbounded/malformed response。它不发送 source body、secret、absolute path 或 private hash，并把 normalized output 存储为 create-only `inferred` sidecar。Ollama 自身的 network behavior 是明确披露的 residual risk。

## 提交 package

官方 portal upload 使用 **Skills only** 类型。Skill bundle 提供 portable analyzer、workspace CLI、workbench、可选 local LLM helper，以及 Windows/macOS/Linux local MCP configuration workflow。Complete GitHub package 还提供 stdio MCP executable 和 automatic launcher。

生成 portal-safe archive：

```bash
python3 scripts/build_skills_only_release.py
```

生成的 ZIP 包含 manifest、skill、script、reference、license、notice 和 icon。此 Skills-only ZIP 用于 portal 的 Skills upload，complete ZIP 用于 local plugin installation 和 GitHub distribution。

## 评估用例

[evals/cases.json](../../evals/cases.json) 包含 positive 和 negative reviewer case，覆盖 preflight、initialization、relation evidence/adapter coverage、保守 Java call、golden/forbidden quality expectation、Spring/Python analysis、version comparison、lineage、local-LLM consent 与 boundary。本文档本身不声明任何特定 build 或 CI 已通过。

## 法律与政策材料

- [LICENSE](../../LICENSE)
- [NOTICE](../../NOTICE)
- [PRIVACY.md](PRIVACY.md)
- [TERMS.md](TERMS.md)
- [SECURITY.md](SECURITY.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)
- [SUPPORT.md](SUPPORT.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TRADEMARKS.md](TRADEMARKS.md)
- [SBOM.spdx.json](../../SBOM.spdx.json)

提交前，publisher 必须核验 developer identity、listing、availability、release note，以及适用法律与 policy attestation 的准确性。
