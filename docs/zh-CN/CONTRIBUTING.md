# 贡献指南

[English](../../CONTRIBUTING.md) | [한국어](../ko/CONTRIBUTING.md) | [日本語](../ja/CONTRIBUTING.md) | [简体中文](CONTRIBUTING.md)

贡献必须保留确定性、本地优先和最小权限的默认设置。

## 文档本地化

对任何面向用户文档的变更，都必须在同一次变更中更新对应的英语、韩语、日语和简体中文文档。提交前运行 `python3 scripts/validate_documentation.py`。隐私、条款、商标、notice 和第三方声明材料的译文仅供参考，并且必须保留共享的英文权威标记。不得翻译或替换 `LICENSE` 或随附依赖项的许可证文本。

提出变更前：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
```

## 版本与发布记录

每项受跟踪的发布变更都要求新的语义化版本和注明日期的 `CHANGELOG.md` 条目。默认使用 patch 版本；当变更扩展能力或破坏兼容性时，使用 minor 或 major 版本。CI 会将 pull request 与其 base branch 比较，并将主分支 push 与其上一 revision 比较；除非 manifest 版本高于该基线且新的变更日志条目位于首位，否则受跟踪的变更会失败。

发布版本前：

1. 同步插件 manifest、运行时常量、SBOM、评估元数据、发布验证器、CI 制品路径、测试和当前版本文档中的版本。
2. 在最终源代码状态上运行完整测试套件和软件包验证器。
3. 将两个确定性发布 profile 各重新构建并验证两次，确认其字节和 checksum 一致。
4. 根据最终提交的源代码状态刷新已注册的自本体，并向其血缘追加 declared 的版本政策事件和 validated 的发布证据事件。
5. 仅在最终 commit 和所需 CI 检查完成后创建发布 tag。绝不移动或替换已发布的 release tag。

只能使用合成 fixture。不得提交私有仓库、第三方源代码摘录、凭据、真实项目本体制品、模型权重或复制的专有 schema。

添加网络访问、目标代码执行、软件包安装、认证、遥测、持久服务、hook、可写 MCP、外部数据库或自动模型下载的变更，需要独立设计，并更新隐私、安全、威胁模型、测试、SBOM 和提交审查。

提交贡献即表示您声明自己有权依据 Apache-2.0 许可该作品。
