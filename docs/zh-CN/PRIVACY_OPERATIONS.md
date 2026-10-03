# 隐私操作 — 0.8.1

[English](../../skills/manage-code-ontology/references/privacy-operations.md) | [한국어](../ko/PRIVACY_OPERATIONS.md) | [日本語](../ja/PRIVACY_OPERATIONS.md) | [简体中文](../zh-CN/PRIVACY_OPERATIONS.md) | [Русский](../ru/PRIVACY_OPERATIONS.md)

## 将私人标识保留在本地

对受支持的生成本体产物、本地 MCP 响应及离线 HTML 应用本地隐私检查。已配置私有资料可拒绝指定实名和个人邮箱，通用检查也拒绝私人邮箱形式的值。公开代码、fixture、包信息、报告和测试输出不得包含真实个人信息。公开发布者仅使用 battle-doll 昵称。

`CODE_ONTOLOGY_PRIVACY_FILE` 指向受保护源码及输出根目录之外的私有配置。配置存储私有密钥、有界长度及 HMAC-SHA256 指纹，不存原始身份文字。配置本身也是私有资料：不提交、上传、打印密钥或指纹，不嵌入 HTML/JSON/MCP。每次重新读取，拒绝链接、reparse point及无效或过大的配置；POSIX要求 `0600`。Windows仍使用原本地ACL，此检查不保证ACL正确。遵循真实runtime契约，不发明设置命令。

失败仅暴露类别，不暴露匹配值。缺少可选配置不提供实名保护，也不能自动识别所有未知姓名。JSON/HTML entity/percent/unicode-escape最多解码3轮，仍可继续解码的值以 `encoding_depth` 拒绝。正规化有限，不能保证任意二进制元数据、图中文字、第三方输出或全部编码。不要将本地 PASS 说成所有地方的隐私清零。

## 分别审核各公开路径

公开 PR 前要求可信、最新的记录，确认实际 GitHub 账户的邮箱保护。手写确认、本地 `git config`、配置资料或单元测试不是当前服务确认。审计全部选定源码和服务自动生成commit ref；仅检查HEAD会遗漏部分保留的PR merge ref。直接branch测试验证代码，不保证未来服务生成commit安全。

官方目录的真实公开开发者身份另行确认。若不只显示battle-doll而可能公开个人信息，在上传、提交、发布之前使用 **HOLD**。上传文件、门户草稿检查、批准和公开listing分别记录。保留ref的泄露在服务确认删除之前仍未解决，不因branch或本地仓库变化声称全局删除。

## 保留产品及验证限制

在完整源码checkout或full发行包中安全配置 `CODE_ONTOLOGY_PRIVACY_FILE` 后，用Python3.9以上及已认证GitHub CLI执行只读发布者检查。

```sh
python scripts/check_publication_privacy.py
```

配置必须含姓名和邮箱两类非空deny列表。检查仅用昵称的manifest、共享scanner扫描的本地Git `--all` 身份/消息/ref名称、公开GitHub配置(name为null/空/battle-doll/배틀돌，email为null)、PR标题/正文及REST每个 `merge_commit_sha` 的author/committer/消息。最多读取100个PR，每个PR最多2次API；满100条的页面、不可读数据或时间预算耗尽均为UNKNOWN。排除未获取、已删除及服务内部ref、历史源码blob、issue/comment、CI日志及图像像素。无法确认GitHub邮箱保护UI或OpenAI选择的已验证身份，因此机械检查通过后仍 **HOLD** 并返回退出码1。没有手动 `--verified` 绕过。可选 `--output` 在源码外保存已净化JSON，findings仅含规则、PR编号和计数；记录不授权PR或上传。此发布管理CLI不在skills-only中，也不为生成器、MCP或HTML增加网络行为。

支持 Windows、macOS、Linux。AI使用只读本地 MCP，人使用要求生成的离线 HTML。本patch不建立额外HTML报告、远程endpoint、telemetry或个人身份上传流程。保留用户模型和推理强度。

HTML选择复制字段使用snapshot/entity/edge相对query，不使用完整本地file URL。自由搜索文本不保存或回放到URL/history，native JSON parse错误原文也不在UI输出。

在最终候选上验证源码、选定ref、解包隐私及两个exact release profile。不变动原0.8.0标签。合成回归只证明相应案例的检测，真实主机E2E、专业翻译、全部无障碍及外部服务删除需要独立证据。[翻译覆盖](../TRANSLATION_COVERAGE.md)明确5语言指南及实际范围。
