# 0.9.0 本地本体流水线

[English](../PIPELINE_0_9_0.md) | [한국어](../ko/PIPELINE_0_9_0.md) | [日本語](../ja/PIPELINE_0_9_0.md) | [简体中文](PIPELINE_0_9_0.md) | [Русский](../ru/PIPELINE_0_9_0.md)

开发者：**battle-doll（배틀돌）**。本地MCP供AI客户端使用，人通过生成的离线HTML查看结果。继续面向Windows、macOS和Linux。原生操作系统测试结果和实测容量与单元测试分开报告。本流程不会提交或发布插件。

**0.9.2 HTML** — 生成的HTML重新以动态3D工作台作为首页。通过“全部记录”可打开目录和策略；地图保留有界分页、全局/聚焦模式及减少动态效果设置。

## 开始与更新

使用Python 3.9或更高版本以及可信的已安装软件包。下文的`COMPANION`指包内的`skills/manage-code-ontology/scripts/companion.py`；Windows可以使用`py -3`。请选择位于已授权源代码之外的新工作区。在导出HTML或可移植包之前，将`CODE_ONTOLOGY_PRIVACY_FILE`设置为源代码和输出根目录之外的私有身份拒绝配置文件。该配置不会复制到知识产物中。缺少保护配置时，导出会报错。

```sh
python3 "$COMPANION" analyze --repo /path/to/source --workspace /path/to/knowledge --authorized --language en
python3 "$COMPANION" refresh --workspace /path/to/knowledge --language en
python3 "$COMPANION" pipeline-status --workspace /path/to/knowledge
```

大量源码可在`analyze`中添加`--capacity large`：上限为250,000个文件、4 GiB输入、500万条记录、8 GiB快照输出与7,200秒。默认仍为25,000个文件和512 MiB输入。这是显式预算选择，不保证所有实际项目都能处理。HTML与可移植导出仍有独立的1 GiB输出限制；只需已封存知识时使用`--no-html`。 每文件AST上限默认为20,000个节点，`--capacity large`为200,000个节点；源码字节、规则IR和深度限制仍生效。

第一条命令构建已封存的知识，创建私有的所有者访问策略，为MCP注册工作区，并生成五种语言的HTML。`--source-root`可以重复指定。`--no-html`仅执行分析。`--label`接受安全的项目别名。更新会保留旧快照、复用未变更文件的事实，并重新构建跨文件解析结果。取消或失败时保留上次已发布的快照；`pipeline-recover --workspace /path/to/knowledge`恢复或完成经过验证的中断本地运行。运行期间源代码或目录标识发生变化时，不会发布新一代结果。

新流水线工作区使用`pipeline.json`和不可变的分区SQLite快照。现有`init`/`sync`工作区和大型项目目录继续兼容，不会被悄悄转换或合并。流水线状态检查验证已保存产物，不打开源文件，并报告`freshness=not_checked`。更新才会重新验证源代码。

## 分析范围

| 系列 | 已实现边界 |
| --- | --- |
| Python | 基于AST的声明、导入和受支持的静态关系；受限的类型化纯函数策略提取。动态执行仍未知。 |
| Java、JavaScript/TypeScript、SQL、Vue、XML/MyBatis | 保守的语法、声明、导入和部分框架模式识别，并非完整编译器、SQL方言或全程序证明。动态SQL和反射仍未解析。 |
| Kotlin、C#、Go、Rust、C/C++、PHP | 有界的声明与导入识别，明确报告部分覆盖和未解析语义。 |
| Swift、Dart、Ruby、Scala | 有界的声明与导入识别，不代表完整语言语义或策略提取。 |
| Bash/POSIX shell、PowerShell | Bash函数、source引用、命令、流水线和控制流边界；PowerShell声明与导入。不执行脚本、展开内容或收集秘密参数。引号或heredoc含糊的区域不输出。 |
| LangChain/LangGraph、Kafka、Redis | 部分声明的智能体、工具、图或消息、缓存关系。环境未知的资源保持分离；不收集原始提示词、键、值、凭据或运行成功信息。 |

每个文件都会呈现语言、适配器和规则版本、源摘要、证据位置范围、分析级别及限制。不支持的结构不会被悄悄提升为已解析知识。归档设计中更广泛的框架待办仍是路线图，不代表支持所有SDK或版本。

引擎使用有界文件批次、单写入者和磁盘分区。已实现的执行配置为`workers=1`。引擎API允许明确提高文件数、字节数和记录数预算；较大限制是安全上限，不是已验证容量。图查询使用分页。完整策略评估另有规则预算，超限会失败，而不是用悄悄截断的规则集进行计算。

## 策略知识与AI使用

六个领域候选为`product`、`order`、`display`、`claim`、`settlement`和`delivery`。基于标识符的分类只是候选，并非业务归属批准。策略保留条件、类型化输入、程序顺序、源断言和不支持的边界。支持的Python子集包括带类型的布尔值、整数和Decimal、赋值、提前返回、布尔条件，以及明确支持的算术和舍入。Java和TypeScript支持具有显式类型的纯布尔条件函数；数值策略、框架驱动的策略和动态分派的策略仍不受支持。不支持的调用、异常和循环不会成为已验证策略。确切支持的子集请查看生成的覆盖信息。

四个策略MCP工具为`list_domain_policies`、`query_policy_rules`、`compare_policy_cases`和`explain_policy_result`。另外四个工具是`ontology_pipeline_status`、`ontology_pipeline_search`、`ontology_pipeline_modules`和`ontology_pipeline_coverage`。完整软件包共有20个只读工具，包含原有的12个。Skills-only包含配置指引和分析器，不包含MCP服务器。

1. 使用`ontology_list_workspaces`并选择一个`pipeline`工作区。
2. 从`ontology_pipeline_status`取得具体快照ID。
3. 所有相关读取都固定该ID。查询固定标识不接受`current`或任意文件系统路径。
4. 读取规则后，提供明确的类型化上下文以解释或比较结果。规则声明Decimal的金额使用十进制字符串。

默认权限视图是`verified_implemented`。`AI-proposed`不参与计算。`approved_business`需要独立、明确的批准元数据，不能从提取成功推断。模型身份与语义验证是不同事项。默认引擎不使用模型，标记为`modelNotUsed` / `N/A`。不会添加云API、安装模型、自动切换模型或传输源代码。

策略问答使用已封存的策略快照，不重读代码，也不查询实时数据库、消息代理或缓存。缺少资格、使用次数、配置或时间输入时，结果保持`needs_context`或`UNKNOWN`。给定样本中的最大值为`best_found`。`proven_maximum`/`proven_minimum`要求完整的受支持范围、精确固定的快照和规则集，以及对独立已知有限输入的穷举；其声明范围绝不代表组织中的所有策略。提取出的源代码行为不是业务批准，也不是实时资格证明。

宿主可能将本地MCP响应转发给远程模型。授权本地源代码分析不等于授权此类传输。请单独选择并批准要发送的证据。

## 知识访问权限

`access.json`是私有本地策略。初始化只授权由操作者绑定的化名所有者。可信启动环境通过`CODE_ONTOLOGY_PRINCIPAL`选择主体，默认值为`local-owner`。工具参数不能指定主体或角色。不同的可信主体绑定应使用分别配置的MCP进程。这是本地进程与操作系统账户边界，不是远程登录服务或身份提供者。

权限为`read_structure`、`read_policy`、`read_evidence`、`export_html`、`export_bundle`和`manage_access`，还可限定到特定快照ID。未知主体、缺失或不安全的ACL、不支持的操作和快照不匹配均默认拒绝。仅策略查询响应保留不透明的证据ID，但不提供源位置详情；这些详情需要单独的证据权限。旧工作区仍仅允许本地所有者访问。权限变更在后续请求中重新读取，不会被缓存为永久授权。

显式调用的本地操作者命令会替换某个主体的授权；MCP不提供该命令：

```sh
python3 "$COMPANION" pipeline-access --workspace /path/to/knowledge --principal policy-reader --action read_policy --snapshot SNAPSHOT_ID
```

省略`--action`会撤销该别名的操作权限。必须至少保留一名不受限制的访问管理员。使用别名，不使用真实姓名或邮箱。领域推断不是授权标签：此版本不声称提供可信的行级领域隔离。不同保密边界应使用分别授权的独立工作区。

HTML导出需要`export_html`及全部三种读取权限。可移植导出需要`export_bundle`及全部三种读取权限。生成的HTML是离线副本；之后更改ACL无法撤销已有副本。应分别保护导出文件并管理接收者。POSIX所有权和模式检查以及可用的Windows句柄ACL检查在不满足要求时拒绝操作；原生Windows执行需要独立验证。

## 人用HTML、数据血缘与交换格式

生成的HTML提供韩语、英语、日语、简体中文和俄语版本。目录、模块、记录和策略决策采用有界页面和精确证据锚点。搜索和3D仅覆盖当前显示页，全部记录可通过分页访问。保留原有3D选择放大与全局控制、减少动态效果、文本导航和移动触摸目标。相对链接无需`fetch`或必需的HTTP服务器即可离线工作。静态页面不代表源代码当前状态或运行行为。

RDF 1.1 Turtle使用[PROV-O](https://www.w3.org/TR/prov-o/)表示断言与来源。[SHACL](https://www.w3.org/TR/shacl/)检查必需的形状属性，不认证事实真实性。快照清单关联产物校验和、分析规范、覆盖信息和源验证时间。校验和是完整性证据，不是可信签名。私有源清单、缓存、访问策略和本地配置不包含在可移植导出中。可移植性从不意味着获得上传权限。

此前的[0.9.0设计基线](NEXT_ARCHITECTURE_0_9_0.md)记录了预期架构和验收目标。本实现指南和生成的验证记录说明实际支持范围；未实测性能、原生设备检查和未来适配器明确保持未验证。官方提交、批准和发布不属于本地工作流程。
