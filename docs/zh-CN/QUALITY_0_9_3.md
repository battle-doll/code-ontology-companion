# 质量改进循环与忠实传递 — 0.9.3

[English](../QUALITY_0_9_3.md) | [한국어](../ko/QUALITY_0_9_3.md) | [日本語](../ja/QUALITY_0_9_3.md) | [简体中文](QUALITY_0_9_3.md) | [Русский](../ru/QUALITY_0_9_3.md)

开发者：battle-doll。保留本地 MCP、供人阅读的离线 HTML、五种语言及 Windows、macOS、Linux 支持。

## 当前公开源流水线的人用视图

公开`analyze`、`refresh`和普通`pipeline-html`默认使用有界human表示：领域 → 主要结构模块 → 核心概览，默认2层、最多3层。每屏最多32节点、64聚合边；五语言UI共享本地script chunk，搜索仅限当前摘要页。全局模式返回全范围聚合root，相机重置不改变范围。源策略卡是含义UNKNOWN的opaque依据卡，不是条件、计算、例外的完整自然语言说明。准确的深层数据保留在MCP。`--presentation records`、legacy workbench和显式partitioned record export仍是独立支持路径，不表示每个business export都变成人用摘要。HTML抽象不能删掉回答或策略文档所需含义。隐私、ACL、当前源绑定与失效检查始终必需。

## 可重复的事实到策略文档质量流程

先于prose建立事实worksheet，记录snapshot/依据ID及每项必需和已支持事实的evidence mapping。保留所有条件操作数、AND/OR分组、真假分支、提前退出、单位、公式、舍入、例外、权限、所有权、ID、状态、精确时间边界（`<`与`<=`）和恢复行为。枚举闭集，明确标注遮蔽、未支持、未知，不猜值也不当作不存在。按实际`controlFlow.kind`分类guard：`synchronized`、`try`、`if`、`switch`不是loop，只有实际迭代结构才可称loop。

文档契约与实现强制、静态观察与runtime依据分别处理。检查各项义务后再写prose，双向核对每句话的依据和每项必需事实在prose中的表达。提取worksheet本身不是完整策略叙述。HTML抽象不能正当化必需含义的遗漏。文件处理、声明/类型、exact calls、策略语义、MCP传递、文档coverage六个维度分开，保留原分母、失败、遗漏、UNKNOWN，不混合总数或编造部分分。

保留已支持事实的evidence mapping防止回归。只有证明精确相同hash及影响范围/可达性并明确parent/new consumer pins时才复用验证，否则重验改变范围。Hash相同也不能免除隐私、ACL、源绑定和失效检查。此通用流程不产生特定应用答案、runtime主张或额外parser支持。

原始表达式列表、opaque guard标签和位置式constructor tuple不会自动成为人的策略含义。写prose前，把已证明的声明/constructor/component/accessor/helper/provider binding连接到命名参数和结果字段角色，完整确认状态、效果、前提、权限及例外含义；未声明的单位或效果保留UNKNOWN。将相关事实分类为ESSENTIAL → 正文段落、SUPPORTING → 机器索引、ALREADY_COVERED → 指定段落、UNKNOWN → 明确原因。不要用全部AST node转储代替策略解释，也不以抽象为由悄悄丢弃必需事实。文档意图、静态依据与runtime强制始终分开。

**Legacy / 显式records workbench范围** — 供人阅读的 HTML 通过 `data/` 共享分页原始记录，供五种语言共同使用。离线脚本提供易读的 JSON 视图与原始值搜索；脚本无法加载时仍可通过静态 JSON 链接查看。所有记录、来源固定信息、隐私检查与输出限制保持不变。请完整保存导出的文件夹。

深层 JSON 字段可能使用 `companion.flat-json.v1`。通过有序 `nodes` 表及 `$ref` 还原 `root`，并验证 `originalSha256` 与 `sourceBinding`。记录 ID、证据和分页信息保持不变。这是无损传递，并非新分析或新权限。现有字节、节点、深度和隐私限制继续生效。

Java 声明保留泛型参数、注解、throws，以及头部、声明、主体的独立范围。类型引用提供原始文本、解析类型或 null，以及解析原因。即使唯一声明允许建立静态调用关系，未解析的类型信息仍会保留。歧义候选不计为精确调用，静态解析不能证明运行时的实现选择。

策略片段保留受支持语法的控制上下文与操作顺序。不透明字面量、未解析调用、运行时分派及未知单位保持显式标记。语法本身不能证明业务规则可执行、已批准或语义完整。

敏感表达式可保留 `structuralOnly` 调用、引用、赋值和控制结构，同时将数字、带引号的值和布尔值替换为 `masked_value`。null 仅作为源码标记保留。嵌套延迟执行主体继承敏感上下文。这些片段仍为部分表达，不赋予值、标准 API、单位或记录结构验证。不得将被遮蔽的值当作零、false、空字符串，也不得猜测其内容。

仅当静态类型和重载证据能够确定标准签名时，受支持的 Java 库操作才提供 `expression.staticContract`。应在同一片段的 `standardApiContracts` 中解析 `contractId`，它不是可单独查询的记录。目录根据一手规范记录算术、舍入、单位和异常条件，但不证明实际值、执行或动态分派。enum 构造器关联保留参数顺序与直接字段赋值；有歧义或条件性的关联仍标记为候选。

对于已选择且可访问的 Java `record`，当接收者、组件类型、源码范围和声明证据得到确认时，隐式无参组件访问器可提供声明的静态返回类型。`staticAccessorBinding` 保留组件证据，并优先采用显式无参访问器声明。在组件和工厂返回值链中，也检查调用者所在包及顶层类型内部的访问权限。尚不支持的泛型或局部 record、不可访问的类型、名称遮蔽与歧义仍为 UNKNOWN。此返回类型连接不增加精确的 `CALLS` 边，也不证明组件值、运行时分派或执行成功。

请获取固定快照的所有 MCP 分页。字节上限错误需要缩小页面，不能当作空结果成功。失败 ID 保留在传递分母中，先还原扁平记录再解释嵌套条件，并获取类型契约引用的调用位置证据。该引用集合不是全部源码调用的分母。

判定引用缺失前，应检查内嵌的 `references[].declarations[]`。参数的词法标识可在其中附带源码位置和类型定义，而不一定是可独立查询的记录 ID。引用包含该定义的实际 MCP 片段，并区分定义缺失与运行时参数值未知。

固定源码哈希、范围与验收标准 → 生成知识 → 查询实际 MCP 分页 → 仅根据本体编写文档 → 与独立从源码导出的标准比较 → 合成测试复现 → 修改产品 → 相同输入重复。另行保留未用于修改的验证案例。

分别报告文件处理、声明与类型、精确调用、策略语义、MCP 传递和文档覆盖率。失败项保留在原始分母中。不给部分描述任意半分，也不将源码补充计为本体独立成功。源码、快照、分析、模型/提示或文档变化后必须重新验证。UNKNOWN/PARTIAL 是有效结果。

可选的私有 `companion.reviewed-literals.v1` 契约可保留经独立审查的非敏感策略值。通过 `analyze --literal-review FILE` 或 `refresh --literal-review FILE` 明确选择。它绑定源码指纹、文件哈希、准确的 UTF-8 词元字节范围和哈希，不接受全局字符串白名单。私有工作区保留契约供刷新与恢复使用。输入变化后，必须重新审查或用 `refresh --clear-literal-review` 明确清除，才可继续复用。现有隐私和敏感上下文拦截保持生效。所有请求保留为允许、拒绝或未观察到；允许不代表提取或文档完整。审查元数据是受信调用方提供的输入，不是身份认证或公开授权。清除仅影响后续快照，已有快照和导出副本保留内容。

顶层字段为 `format`、`purpose`（`private-policy-analysis`）、`sourceFingerprint`、`review`、`entries`。`review` 记录 `reviewId`、`reviewerKind`（`independent_source_review`）、`reviewedAt`。每项记录 `path`、`sourceSha256`、`tokenByteStart`、`tokenByteEnd`（不含结束位置）、`tokenSha256`、`classification`（`nonsecret_policy`）、`reasonCode`、`usageContext`、`reviewId`。范围包括引号；原因和上下文代码不含源码值。启用审查时，未审查的带引号值均保持遮蔽，包括原先由类型化小数提取处理的数字字符串。审查文件须私密保存。CLI 不会从源码文字推断授权，也不会自动寻找审查文件。

数组初始化器和注解参数保留源代码中的顺序、结构及绑定到准确出现位置的审查证据。注解目标仅提供源码声明证据；适用性、框架路由和运行时行为仍为 UNKNOWN。敏感上下文中的仅结构片段，可在精确源码字节、请求索引和隐私检查通过后保留经审查的零长度字符串作为空标记。其他敏感值遮蔽、出现位置隔离和撤销机制保持不变。

文件级 `literalReviewDelivery` 衡量输出片段树中的保留情况。快照摘要的 `literalReviewRetention` 分别统计获准、保留和未保留的出现位置，并在每个 `SemanticCoverage` 记录中留下未保留的请求索引。许可、输出保留、MCP传递和政策语义完整性分别验证。获准项为0时标记 NOT_APPLICABLE，而非100%。

Java 源码注释使用另一项可选的私有契约 `companion.reviewed-documentation.v1`，通过 `analyze --documentation-review FILE` 或 `refresh --documentation-review FILE` 明确选择。默认情况下，所有已识别的行注释、块注释和 Javadoc 只保留不含原文的位置与哈希元数据。只有经过独立非敏感审查的准确出现位置，通过现有隐私配置和内置检查后，才将原始词元放入 `sourceText`。原文及去除格式的检查表示都接受检查；检查用的规范化结果不会替换输出原文。

文档审查 manifest 的顶层字段为 `format`、`purpose`（`private-policy-analysis`）、`sourceFingerprint`、`review`、`entries`。`review` 包含 `reviewId`、`reviewerKind`（`independent_source_review`）和 `reviewedAt`。每项包含 `path`、`sourceSha256`、`tokenByteStart`、`tokenByteEnd`（不含结束位置）、`tokenSha256`、`classification`（`nonsecret_documentation`）、`reasonCode`、`usageContext`、`reviewId`。指纹、文件哈希、UTF-8 字节范围和哈希绑定包含注释分隔符的完整准确词元；行注释不包含换行符，不接受子字符串。manifest 不得包含源码原文或实际值。上限为 512 KiB、5,000 项及每个注释词元 8,192 字节。

保留的注释是不可信的引用源码数据，保持 `instructionAuthority=none`、`documentation_claim`、`enforcement=UNKNOWN`、`target.resolution=UNKNOWN`、`businessMeaningVerified=false` 和运行时 `not_observed`。仅凭回调声明不能确定注释的声明目标。注释主张不能替代代码证据，也不能证明实现已强制执行或授予公开权限。审查元数据是调用方提供的来源信息，不是身份认证。

私有工作区保留所选文档审查契约以供刷新和恢复。输入变化后，需要匹配的新审查或使用 `refresh --clear-documentation-review` 清除。清除仅影响未来快照；旧快照和导出副本保留内容。`DocumentationCoverage` 明确记录未审查注释、允许／拒绝／未观察到的请求和遗漏。已识别词元清单的覆盖率与 `lexicalComplete` 分开报告；不支持的语言、Java Unicode 预处理或未确认的词法边界使注释总分母保持 UNKNOWN。预算导致的遗漏保留数量和原因，并标记清单不完整。注释和表达式片段共享现有的每文件预算；获准或传递均不代表策略完整。

下划线强调格式的边界不明确或超出支持范围时，以 `unsupported_documentation_format` 拒绝；独立审查不能绕过此限制。

受支持的增强for头部保留迭代变量声明、被迭代表达式和内联循环体定义。数组元素顺序、循环体条件、提前退出及累积更新候选保留源代码关系。实际遍历、迭代次数和到达值仍为UNKNOWN；不支持的头部和不透明字面量也会明确记录。

当`resolution=selected_static_final_field`时，`staticFieldBinding`将唯一且可访问的已选源代码static-final字段连接到声明及初始化片段，不替换初始化值，也不证明运行时初始化。`recordConstructorDeclarations`将隐式canonical构造器参数按位置连接到声明的record参数。显式或compact构造器保留候选和未确定的值传递，不生成虚构的精确CALLS或运行时字段值。

文档化的标准重载包括十进制余数和纳秒减法。余数可能为负，不等于始终非负的modulo。MathContext约束内部整数商，而余数计算本身是精确的。时间契约保留单位和异常条件；数字类型本身不能确定业务单位。

在请求独立记录之前，应先在所属片段中解析`source-body:`、`source-binding:`和`source-record-constructor:`的定义。循环引用标明定义片段及循环体位置，构造器引用标明本地声明目录。源字段引用必须连接到实际声明和初始化片段。`sourceRange.charStart/charEnd`使用从0开始、末端不包含的Unicode码点范围；已审核字面量及注释manifest使用UTF-8字节范围。两者都应检查snapshot、源哈希及引用定义的闭合关系。

最终审核中，定义缺失、不匹配或被撤回时，依赖它的类型、访问器、构造器及API证据也会被撤回。原始语法和独立的其他证据仍保留。依赖证据闭合尚未确认时不能完成最终snapshot，也不能将UNKNOWN提升为已证实的结论。

管线 RDF 对语义片段（包括覆盖率、遗漏和已审查文档）保留供现有查询使用的 `co:Symbol`，并添加 `co:SemanticFragment` 与实际的 `co:extractorVersion`，不会用虚构的 `ruleVersion` 替代。SHACL 要求语义片段具有提取器版本，同时仍要求普通符号、断言和策略规则具有 `ruleVersion`。这只是有界的元数据投影，表达式 AST 和已审查注释全文并未完整导出到 RDF。形状验证通过不证明完整 JSON/AST 等价性、完整 PROV 语义、策略完整性或运行时执行。仅生成文件不会改变独立 RDF 验证的 `not_run` 状态。

Java Record 符号通过 `recordComponents` 提供独立于构造函数调用的组件声明。组件顺序、名称、声明类型及已解析/UNKNOWN 类型对均绑定父 record ID、路径、源哈希和字符范围。`recordHeaderRange` 包含组件列表的括号；`recordComponentCoverage` 区分已知原始数量、输出、遗漏和不支持的条目。目录最多输出64个组件，但不截断共享解析器或改变现有字段、调用分析。过长文本会被隐藏并注明原因。未确定类型保持 null/UNKNOWN；语法异常或不完整清单保持 PARTIAL。不包含注解参数值。观察到声明不证明存储值、运行结果或额外的精确 CALLS。

应按 `resolution` 区分 `staticFieldBinding` 和 `receiverStaticFieldBinding`。`selected_static_final_field` 需要已交付的源字段声明和初始化证据。`declared_record_component_field_type` 则对照实际父 Record 及其 `recordComponents` 声明，不要求初始化证据或构造函数调用目录；运行时值仍为 UNKNOWN。接收者绑定应对照 `receiverStaticType`，不能与调用结果类型混淆。未知 resolution 保持不支持。冲突的显式 import 使组件类型保持 UNKNOWN；void 组件和非末尾 varargs 记录为 unsupported/PARTIAL，不缩小已观察清单。

Java 块内的 `var` 局部变量仅复用与源文件绑定的表达式分析已证实的初始化表达式静态类型。`localTypeInference` 将声明、初始化表达式和词法作用域范围绑定到文件哈希；使用处通过 `localTypeBinding` 引用该定义。引用保持精简，并遵守已有依赖深度限制。未知、语法无效、自引用、多声明符、已遮蔽或不支持的初始化表达式保持 UNKNOWN。定义缺失或撤回时，依赖的类型/API 证据也会撤回，同时保留原始语法与独立证据。已输出 `var` 声明的统计与原始片段清单中的遗漏分开报告。这不证明数值、确定赋值、通用泛型推断或运行结果。

重用初始化表达式类型还要求词法范围与 Java 索引中的命名类型及方法归属一致。局部类、匿名类、归属缺失或冲突，以及未证实的外层字段引用保持 UNKNOWN。必须确认最近的成员声明；继承成员可能遮蔽外层字段。归属符号缺失或使用位置归属改变会撤销依赖证据。已有的未支持语句区域继续保留在分母中。

归属证据必须与实际投影的 Java 符号定义核对。sourceRange 等于完整的 declarationRange，bodyRange 单独表示正文，位置单位为 Unicode 码点。declarationSpan 表示完整声明，而 span/headerSpan 可能只表示声明头。受支持的 controlFlow.owner.id 使用实际方法符号 ID。定义缺失、边界篡改、范围不一致、替换成其他方法 ID 或无法查询归属定义都会撤销依赖推断；复制的注释彼此相同并不足以构成证据。

Java 继承名称检查仅在平台身份得到精确绑定时使用有限的 `java-se21-member-inventory-1` 目录。快照和分析规范中的 `javaStaticModel` 将 Java SE 21 作为有效静态模型假设，`actualTargetJdk` 仍为 `UNKNOWN`。`platformTypeContracts` 去重保存字段、成员类型、父类型清单及官方规范链接。简短的 `platformInheritance` 引用指向同一 fragment 或 Record 符号内的 `platformInheritanceChecks`，保留所选源码声明 ID、路径、摘要、头部范围及父类型引用位置。类型符号的 `sourceRange` 和 `declarationHeaderRange` 使用从零开始、右端不包含的字符偏移。这些是有限的词法观察和已文档化的平台假设，不是目标 JDK 探测、完整成员导出、精确 CALLS、执行或运行时值证据。未知父类型、歧义 import、所选源码的平台身份冲突、实际遮蔽成员以及投影上限均保留明确的不确定状态。此模型不推断局部 `var` 类型。

将继承名称不存在作为类型或 API 契约依据前，必须确认每个所选源码作用域所需命名空间的声明清单。`sourceScopes[].memberInventory` 分别记录字段和成员类型状态、已处理的直接声明区域数（不是字段数），以及排序去重的 `fieldNames`。有限的完整直接字段语句支持多个声明符，区分泛型类型逗号与声明符逗号，每个字段初始化式都必须由支持的有限表达式文法完整解析，不计算数值。有效 record 组件头的隐式字段名与支持的 enum 常量直接字段名也进入清单。实际遮蔽名称的字段保留为 present。带注解字段或常量、不支持或无法验证的构造器头、不支持或畸形区域、Unicode escape 边界及检查上限使相关命名空间保持 `UNKNOWN`。此操作不扩展 JavaIndex、精确 CALLS、运行时值或完整策略覆盖率。

完整限定的父类型名或单个显式类型 import 可以独立于无关的 on-demand import 确定已知父类型。未知父类型、冲突的显式 import、未能确定的含糊 on-demand import 仍为 `UNKNOWN`。static on-demand 父类型 import 即使 owner 已被选中，也在缺少独立绑定源码的成员不存在证据时保持 `UNKNOWN`。不会凭名称相似将词法成员类型提升为标准类型。源码返回类型接收者仍要求精确且可访问的源码声明与 callsite，未解决的重载不会获得标准 API 契约。命名空间和 import 规则依据 [JLS 6.5.5](https://docs.oracle.com/javase/specs/jls/se21/html/jls-6.html#jls-6.5.5) 与 [JLS 7.5](https://docs.oracle.com/javase/specs/jls/se21/html/jls-7.html#jls-7.5)。这些是有限静态检查；实际目标 JDK、运行时层级、值及执行仍为 `UNKNOWN`。

内联平台定义同时按 ID 和 canonical JSON 内容匹配。在现有 64 项验证上限内，内容完全相同的重复定义视为等价；忽略对象键的顺序，但区分数组顺序和 JSON 值类型。同一 ID 对应冲突内容时，不按数组顺序选择优先定义。相关类型与 API 依据变为 `UNKNOWN`，并记录 `platform_inheritance_definition_conflict`；独立的兄弟表达式依据仍保留。源码模型和 6 项 canonical 平台契约内容不变。

`platformInheritance` schema 2 将每个类型使用位置连接到有界的 `platformTypeProofs` 图。直接依据标识实际交付的声明或源码语法位置，以及所属类型、类型写法、命名空间、路径和源码哈希。传播依据指向同一 IR 记录中实际的接收者、参数或操作数位置；标准 API 签名及输入、返回类型与共享目录核对。因此，基本类型返回值可以沿用接收者的类型解析依据，而不把两者的类型视为相同。缺失、冲突、撤销或错误重绑定的依据变为 `UNKNOWN`，独立兄弟依据仍保留。canonical 内容相同的重复项在现有限制内等价。检查与类型证明合计仍限 64 项，共享目录、检查和证明合计仍限 64 KiB；循环、深度或遍历超限均不作确定结论。类型及方法的声明和正文范围、有界 import 观测及精确 callsite ID 用于核对。内联证明 ID 和 JSON pointer 不是可单独查询的源码记录。这是声明的 Java SE 21 假设下的静态源码依据；实际目标 JDK、运行时值、分派、执行及业务策略完整性仍为 `UNKNOWN`。

`platformTypeProofs` 定义的有效性缓存不能替代对每个实际使用位置的验证。复用已缓存的依赖结果前，必须核对 IR 位置、角色、类型及检查引用。无论遍历顺序如何，其他使用位置的有效证明都不能作为当前使用位置的确定依据。

可选业务知识覆盖层保留源快照和现有 3D 地图。独立的离线五语言视图展示所有选定业务记录、有向关系、策略的单位・时间・组合要素、源沿袭及相互独立的依据与批准状态。缺失或不支持的要素保持 UNKNOWN。知识批准不授予执行权限，也不证明运行时行为或整个策略的完整性。源、规范或审查发生变化时必须重新验证，并保留原始选择、失败和遗漏分母。

业务 HTML 或打包导出同时要求 export_html/export_bundle、read_structure、read_policy 和 read_evidence。可信回调在发布锁内重新检查精确的源与业务标识、ACL 修订、当前隐私配置及稳定读取器。导出创建新的私有目录，保留每条原始业务 JSON 与范围，使用惰性文本和相对离线链接，并与源输出共享既有总计 1 GiB 预算。RDF 1.1/PROV 和声明的 SHACL shape 附带逐记录映射损失报告及原始 JSON 引用。序列化或 shape 通过不能证明业务事实。原生浏览器与 shape 验证在独立执行前保持 NOT_RUN。后续 ACL 或撤销变更不能撤销已导出的副本。开发者：battle-doll。

有界 TypeScript boolean 策略解析器可保留与具名空类，或以分号结尾且无初始值的 `boolean`、`number`、`string` 字段共存的纯类型化函数。支持类前直接出现的可选 `export`。类会作为实际模块绑定解析并保留，因此不会忽略类与函数重名或内部类型名遮蔽。初始值、static 块或成员、方法、继承、decorator、计算名称等不支持形式仍为 `UNKNOWN`，不会从已选源码中删除类。`source_policy_declaration` 使用 `source-policy-declarations-1`，保留路径、源码哈希、行范围、lexer token 索引范围、非策略选择状态及运行时限制。这些是声明观察，不是可执行策略公式或运行时字段值的证明。独立的 `sourceDeclarationCoverage` 保留在封存策略汇总和 MCP 中，不增加策略规则数量，也不证明业务策略完整性。现有预算保持不变；声明记录被省略时阻止新快照发布。该 lexer 不声称字符或字节 offset。

局部 `var` 的类型证据可以通过精确的初始化表达式记录，延续有限的平台继承证据。`platformTypeProofs` 中 `kind=local_initializer` 的直接来源指向实际输出的局部声明及其 `/expression/staticType` 证明；每个使用位置保留独立的证明 ID。仅在现有上限内去重传递所需的检查和目录定义，同时核对实际局部绑定、声明与使用范围及方法所属类型。缺失、撤销、冲突或超出上限的依赖仍为 `UNKNOWN`，并保留源码结构与覆盖率。这是静态类型证据的组合，不证明运行时值、执行成功或精确调用解析。

独立的源码声明覆盖统计从封存策略汇总传递至源码 HTML、业务候选覆盖统计、只读 MCP 和业务 HTML。审查或撤销后仍保留原始源码分母。旧版或非 TypeScript 缺少统计时标记 UNKNOWN，不推测为零。只传递固定范围与原因代码、非负整数计数及明确完整性标志。声明清单不增加策略规则数量，也不能证明业务策略完整性。

直接字段清单还会拒绝保留声明标识符、重复或冲突的字段修饰符、畸形 wildcard bound、缺失初始化式和剩余尾部 token。enum 参数和 record 组件头遵守同样的保守语法边界。复用共享表达式解析器并不等于 javac：非空 anonymous 成员体、带类型/注解/嵌套或未完全解析的未支持 lambda、generic method 参数及有限 IR 无法区分的文法保持 UNKNOWN。因此相近的有效语法也可能因明确的 inventory 原因而暂缓。引号 literal 仅检查结构，不保留数值。该检查仅证明支持的声明语法；compiler 有效性、赋值类型兼容性、执行及实际目标 JDK 尚未验证。

存在精确源码声明范围时，控制流所属项保留独立 declarationSpan。原有词法 span 保持不变，并区分注解或多行头部对完整声明范围的扩展。两个范围绑定相同源码哈希及字符位置。这只细化来源位置，不增加声明、调用、策略含义或运行证据。不会为未解析词法所属项推测声明范围。

## 业务候选分片存储

候选生成默认遍历所选源码快照的全部记录。不可变 SQLite 分片各不超过10,000行和64MiB，并遵守现有源码工作区的记录数、输出容量及期限预算。单条记录、JSON深度、查询、隐私和权限限制保持不变。显式使用 --max-records 请求有限预览，仍保留原始分母及每个省略输入的状态。--partition-size 控制分片行数。每次审查最多10,000个概念，保留全部自动候选、独立批准历史及sourceCandidates分母。源码、规范、权限固定，发布锁、指针比对和原子发布仍为必需。源码同时提供字符与字节范围时分别验证并保留原值，不转换、不回退。当前源码、规范和权限匹配时仍支持旧版v1 JSON。候选全部存储不证明语义完整，业务含义保持PARTIAL，全部业务规则覆盖率保持UNKNOWN。

信任查询筛选及合计前，逐行检查未缓存分片，将索引id、kind、domain和大小写折叠名称与规范载荷及概念ID比对，并再次验证返回行。进程内LRU仅保留最多64个成功的元数据结果，键包含精确路径、完整稳定文件身份、完整产物SHA、模式和生产规范，不缓存记录值。复制、替换、哈希或规范变化及缓存淘汰后必须重新扫描；失败读取器不提交待定缓存。完整性验证与业务语义完整性分别判断。

## 原始记录的共享传输格式

可下载的原始JSON保留既有序列化字节。独立JavaScript传输文件可使用确定性字典和有界共享解码器表示重复键与字符串，解码值与原有JSON.parse方式相同。字典传输文件不比原文件更小的页面，以及包含在JavaScript中舍入为非有限数字的有效JSON整数的页面，使用原有方式。这保留现有浏览器数值精度和范围限制，不会把JavaScript数字变为精确十进制运算。需要原始数值表示的使用方仍可下载原始JSON。字典解码器验证允许标签、引用、重复键、记录数、深度和字节上限。5种语言均保留离线导航、原始下载和既有3D页面范围，不需要fetch或HTTP服务器。传输格式验证与实际浏览器、无障碍、性能及策略语义验证分别判断。

## Java 构造器与泛型创建表达式的有限成员清单

直接成员名称检查能够识别与所属类型名一致的类、枚举构造器头，以及记录类的紧凑构造器，然后跳过括号配对完整的主体。支持的访问修饰符、类型参数、形式参数、末尾可变参数和 throws 子句必须完整解析。每个类型通过 `constructorInventory` 仅记录一次与源码绑定的头部和主体范围，并标注 `constructor_body_semantics_not_modeled`、检测到的有限语法数量、已分析主体数 0，以及 Java 全部声明的分母 `UNKNOWN`。构造器语句、初始化、构造器 CALLS、编译和执行不在分析范围内。

完整解析的泛型及菱形创建初始化表达式保留后续字段名称，支持嵌套引用类型参数及 `List<int[]>` 这样的基本类型数组引用参数。`List<int>`、创建类型的直接通配符参数、不合法或残留的标记、非空匿名主体、带类型/注解/嵌套或未完全解析的未支持 lambda、接收者参数及不支持的注解仍为 `UNKNOWN`。实际名称遮蔽、未知父类型及 Unicode 转义保护仍撤销依赖的 API 注释。原有 ID、CALLS、目标、声明范围、表达式值及运行状态未知保持不变，只恢复受支持的派生静态证据。Windows、Linux 原生验证与 Python 3.9 macOS 验证分别报告。

有界的无类型 lambda 初始化式仅在完整验证参数、箭头、函数体及其余声明符后确认直接字段名。带类型或注解的参数、嵌套 lambda、局部声明、未支持的匿名体、错误语法及超出预算的情况仍为 UNKNOWN。不建模 lambda 执行、函数体类型兼容性或值。选中的 static 通配符字段仅凭精确的直接所属类型及绑定到源码的声明确认；继承遮蔽、歧义及不完整清单仍按失败关闭处理。

单项及通配符 static 字段使用要求 declarationProofVersion=1。实际传递字段的 declaredType 和解析后的类型拼写须与绑定源码的所属类型 ID、名称、种类、路径、digest 及声明/头/体范围一致。每个类型仅记录一次 directMemberInventory；即使没有平台父类型，名称不存在证明也须与该实际清单匹配。缺失或矛盾记录会撤销依赖证据。字符串、字符及空字面量仅检查结构，不保留其值。保持表达式512个 token、参数/语句64项、直接成员区域1,024项及嵌套32层限制。lambda 参数的名称遮蔽仅在其局部范围生效，构造器体仍不建模。

选中的 static 字段还必须匹配实际类型清单中的直接成员声明。头部修饰符、static/final 资格、原始类型及精确的声明/初始化式范围，与实际非可调用体字段角色一起验证；局部声明及初始化块不能冒充字段。实际 caller 声明及完整 import 元数据决定单项导入优先级，或验证所有生效的 wildcard namespace；直接 lexical 引用不新增 import 要求。清单保留已检测、不支持及预算省略数量，最多1,024个候选区域及64 KiB声明，caller namespace 最多64项 import/检查及64 KiB。完整性仅指有界索引声明；赋值兼容性、初始化式求值、编译及全部 Java 字段覆盖仍为 UNKNOWN。

## 访问策略验证与当前权限

每次调用仍重新读取私有权限文件、核对完整字节哈希并重新验证隐私配置。进程内最多复用64个验证成功的策略快照，主体、操作和快照权限每次重新判断。中性样例耗时不代表实际目标性能。

正在进行的调用可能使用已经验证的策略快照完成。后续调用会重新读取策略。

分片导出的每个检查点都基于刚刚验证的一份策略，检查所需的全部五项权限。不返回部分授权，也不缓存授权决定。后续检查点及最终发布前仍重新读取策略，并保留文件安全、隐私和快照检查。

## 导出所选知识全集

保留现有工作区、快照和语言选择，只需为 pipeline-html 添加 --partitioned。根目录页连接源代码地图、完整源 RDF 包及全部业务分片。

```sh
python3 skills/manage-code-ontology/scripts/companion.py pipeline-html --workspace /path/to/knowledge --snapshot SNAPSHOT_ID --output /path/to/export --language zh-CN --partitioned
```

源渲染器保留普通默认值 1 GiB 及现有的正数预算 API。在显式分片导出集合中，它使用工作区已配置输出容量的剩余部分，不修改设置，也不推定新容量。源代码地图、地图视图和五种语言只生成一次。每个业务分片仍最多10000条记录、最多1 GiB，并保留现有记录、页面、深度、隐私和权限限制。验证全部所选记录、原始 JSON、RDF、沿袭、映射损失报告及跨片链接后，才原子发布整个根目录。原始固定标识和分母保持可见；预算不足、取消、证据变化或权限撤销均阻止整个根目录发布，绝不悄然省略记录。私有进度凭证保留受影响组件与分片、原始和已处理数量、字节、耗时及有界重试历史。

源代码地图连同地图视图和原始 JSON 页面，以五种语言生成一次。source-rdf/ 中生成一次仅含源数据的标准包，包括 ontology.ttl、lineage.ttl、shapes.ttl、policy.json、bundle.json、现有 coverage.json，以及保存全部源记录 JSON 的 knowledge.sqlite。现有源数据包不生成独立 JSONL 或映射损失文件，因此不宣称提供这些文件。每个业务分片保留完整规范 JSON、RDF、PROV/SHACL 资料和映射损失报告。源 RDF 与业务 RDF 分别以自身记录范围为分母。

普通默认预算并不保证容纳任意大型所选范围。显式分片模式仅使用已配置输出预算的剩余容量，绝不悄然省略记录。源组件使用剩余总预算，每个业务分片仍最多10000条记录、1 GiB。不把分析或存储的时间限制重新解释为新的导出截止时间；保留显式取消功能，并记录实际耗时。

发布完整结果前，将私有根目录和每个子产物与生成时的文件哈希、字节数、原始固定标识及准确分片成员逐一核对。文件被修改、缺失或新增都会阻止发布。

只有单个分片上限起约束作用时，才缩小记录数重试。如果总剩余容量起约束作用，则保留原始选择分母及失败尝试记录，并以 BLOCKED 停止。两项上限相等时也按总容量约束处理。

完成所有文件检查后，在发布前重新核对当前隐私配置和访问权限。如果发生变化，则保留原始选择范围并阻止发布。

已导出的副本无法远程撤回。最后一次当前策略检查后的变化属于现有的进行中发布边界。

候选存储或导出成功不证明业务含义完整、形式化策略覆盖、实际执行或收益。业务完整性仍为 PARTIAL，全部业务规则覆盖仍为 UNKNOWN。实际完整导出得到测量前，不宣称大规模浏览器可用性和性能已验证。每条业务记录生成五种语言的 HTML、JSON 和 RDF，另有源代码与目录开销；不将小型中性样例 的字节、时间或文件数外推为实际全集结果。

## 可选的显式业务契约

property_type 保留精度、小数位数、舍入、单位、币种和时间信息。formula_mapping 要求当前 source pins、实际 rule digest、精确的 property ID、参数和返回类型以及 /program、/returnType anchor，不凭名称推断。policy_composition 通过唯一优先级及显式互斥和叠加方式选择最多16个成员。缺失、冲突、撤销或不可比较时保持 UNKNOWN。仅拒绝计算引用的重复和循环，允许普通业务关系图循环。目前 eligibility、exclusions 仅支持显式 NOT_APPLICABLE。

时间判断要求带时区的显式 as_of、匹配的 clock/timezone 和区间边界。仅支持 UTC 和固定 offset；IANA/DST 为 UNKNOWN，不自动使用当前时间。finite_contexts 必须与最多100个已审阅 typed 输入完全一致。有限集合 best 不代表全局最大值或执行授权。没有可选契约时，原有单个 source 函数行为保持不变。

既有失败、遗漏和原始分母始终保留。business-build --processing-outcomes 和 review processingContract 可选地保留成功输入 index，用于详细 business coverage_view=processing。accepted/unsupported/rejected/conflicted/duplicate/omitted 与 revoked/invalidated 生命周期分开。未记录的历史范围为 UNKNOWN。数量核对不等于业务语义完整。JSON/RDF 保留规范 typed 契约，RDF 不证明业务真实性。

时间值或维度未知的 property 评估不受支持，保持 UNKNOWN 并保留时间信息。既有 exclusivity/stackability 必须与新 composition 契约一致。分片 export 仅在根目录保存一次全局分页 processing ledger，各 part 引用原 scope、pins 和 manifest hash，并区分自己的 record subset 分母。

仅限政策读取的响应会隐藏公式映射中的源绑定信息、记录摘要和数值上下文摘要，包括序列内的嵌套映射。具有证据读取权限的响应及规范导出仍保留这些证明；投影响应不能复用为审核清单。政策组合的每一层都必须明确适用及排除条件。带时区的业务时刻与源规则的日期有效期分别验证。没有日期限制的函数仍可求值；有日期限制但缺少时钟映射时保持 UNKNOWN。不会使用主机时间或擅自截取时间戳中的日期。

### 精确维度与结果贡献策略

显式数量和金额契约可以保持源代码的 `int` 类型。传输值仍为字符串，`int` 仅接受精确整数写法。分数、`2.0` 等小数写法、浮点值、越界或精度与小数位不匹配均保留为不支持，不做舍入。金额可同时保留明确审核的单位和货币；单位只是声明的维度，不推断定价惯例或货币换算，并须与已有声明完全一致。

`selectedPolicyIds` 保留完整依赖清单。`activeMemberPolicyIds` 列出适用的直接成员，`selectedMemberPolicyIds` 列出优先级或聚合之后贡献结果的直接成员。`contributingPolicyIds` 和 `contributingSourceRuleIds` 标识贡献的末端策略及精确源规则。最小值或最大值并列时保留全部贡献者，嵌套选择及每个最优有限上下文均保留各自沿袭。未解决或冲突时贡献列表为 null，不推测胜者。原始成员和上下文分母以及 `globalOptimum=UNKNOWN` 保持不变。

审核预算导致的未处理输入在覆盖率摘要和原始处理记录中保持相同计数，不从分母中移除。

源引用哈希计算采用独立的 JSON 深度上限 128，内联业务 JSON 的深度上限仍为 32。两条路径均保留 2,000,000 个节点、32 MiB 编码大小、字符串与键长度及有限数值限制。深层源结构通过精确哈希关联，不复制到业务属性，也不视为已批准的语义。超出上限的输入仍以不支持状态保留在原始分母中。先前接受的规范哈希保持不变。

流式交换文件会检查每条完整逻辑记录中的隐私值，并保留已封存的字节和哈希。开始、结束及有界批次均执行最新状态检查：普通输出最多128条记录或64 KiB，每条记录后还会协作式检查是否已过50ms。较大的记录不拆分，单独处理，最大4 MiB。批次内的取消或权限撤销可能比逐条回调更晚被发现；50ms不是阻塞I/O或隐私检查的强制截止时间。不缓存权限决定，最终权限、隐私配置、快照检查和原子发布条件仍然必须满足。分区导出会明确报告源RDF准备阶段。

## 泛型 instanceof 语法的有限支持

Java 能力适配器保留 `Map<?,?>`、`List<?>` 等受支持的无界通配符形式中的检查对象、限定或嵌套类型段、引用数组维度、模式绑定名称、否定及分支上下文。扩展类型节点使用 `op: type_reference` 和 `syntaxVersion: java.instanceof.type.v1`。它们仅表示语法，保持 `partial` 和 `instanceof_runtime_unresolved`；实际类型匹配、编译有效性及目标 Java 版本仍为 `UNKNOWN`。不推断绑定名称的接收者类型、字段值、执行或已批准的业务含义。Java SE 21 只是语法参考，不证明应用的编译器配置。

表达式上限仍为 512 个 token 和 32 次解析器递归入口，并非左结合最终树的所有边深度都不超过 32。扩展类型的限定段、通配符总位置、数组维度各最多 32；共享类型读取器和保守回退扫描各最多消费 512 个 token。原有 plain 限定类型保留原表达式限制。带界限、具体或嵌套类型参数、注解及 record 模式、畸形语法和超限情况保留原位置与原因，仍为不支持/UNKNOWN。

可能的模式名称在所属 callable 内保守阻止冲突的外层或平台绑定；无法确认 callable 所有者时仅限本地块或表达式。扫描超限或所有者不明保留局部不确定原因，不阻断其他方法或文件。现有源 ID 和 CALLS 与此语法能力分开。原始 JSON/MCP/HTML 及源包 SQLite 保留语法，但图形/RDF 投影不证明其完整含义。不能解释必需节点或版本的消费者应保持 UNKNOWN 或拒绝解释，不得丢弃类型或绑定名称。独立策略文档生成验证与原生浏览器行为属于另外的关卡。规则只依据语言语法及来源契约，不使用应用专属文件、方法或业务词条件。

嵌套 lambda 具有独立的 callable 边界，内部模式不会阻断独立的外部调用。API 操作数按实际词法使用位置验证；仅按名称聚合的引用摘要若无法区分不同作用域的出现，仍保持 UNKNOWN。


### 赋值语法与 record 声明的边界

Java 语义片段保留原始赋值运算符，包括算术、位运算和移位复合赋值。对于有限范围内支持的目标，可附加有条件的读取、修改和写入契约；不支持的目标保留位置、原因和未完成状态。该契约不会执行表达式，也不确认目标值、副作用或实际运行行为。

record 成员清单区分 compact 构造器和支持的显式构造器头。有限范围内的重载头与 compact 构造器共存时，不再隐藏已声明的 record 组件。识别构造器头不保证编译有效性、构造器体行为、委托或参数与字段的映射。模糊签名、不支持的语法和冲突声明仍为 UNKNOWN。序列化区域类型 `record_explicit` 是语法元数据；不认识该类型的消费者必须保留原始记录并明确标记为不支持。静态声明和接收者证据与运行时调用选择分别处理。

## 显式比较提供的数值观测

`compare_policy_cases` 默认使用 `comparison_mode=source_contexts`，即使源函数参数名为 `id` 或 `value` 也不推断其他模式。显式 `supplied_values` 要求 `knowledge_view=business`、现有具体 source/business 固定标识和策略读取权限。它不调用源规则或可选策略组合，`sourceEvaluation` 为 null，`sourceRuleEvaluated` 为 false。原有撤销、冲突、批准关卡保持不变。业务记录获批不代表提供值的真实性或资格获批，运行与资格仍为 UNKNOWN。

每个案例恰有 `id`、`value`。ID 必须是无控制字符、不超过128字符的非空唯一字符串。值是原始整数或现有 typed `integer`、`decimal`、`quantity`、`money` 对象。整数绝对值不超过10**100；小数字符串沿用不含指数、不超过128字符的普通文法。有精度声明时验证，缺少时不臆造。整数与小数 scalar 可一起比较，数量要求单位完全一致，金额要求币种与可选单位 tuple 一致。类型、单位或币种混合时，所有原本有效的数值项均标为不可比较，不任取基准组或换算。服务器精确比较所提供的值，但不能恢复客户端已损失的精度。

`suppliedComparison` 保留原始 `inputIndex`、`/cases/<index>`、有效 ID、canonical 输入 digest、处置及原因。缺失、不支持、无效值及所有重复项均保留在原始分母中。minimum、maximum、best 按原顺序返回全部并列 index/ID 引用，值保留在 entries。COMPLETE 只表示所选提供值全部通过本次局部比较；存在未确定或拒绝项时为 PARTIAL，受支持子集不等于整体排名。不证明全局最优或完整策略含义。

在候选或查询 hashing、部分输出之前，对原始 cases 整体进行 privacy 检查；拒绝时拒绝整项请求。案例上限100、canonical cases64KiB，并保留现有整体请求 protocol 上限。内部超限返回含未处理 frontier 的 BLOCKED；protocol 不合法或超限请求在调用前被拒绝，不构成逐项处理证据。查询标识绑定原案例、目标、模式、当前固定标识及获准的策略投影。仅读取策略的用户不会额外获得隐藏的记录级证据 digest。


## 显示未完成的处理状态

已识别的类型化策略函数会保留已提取、不支持或未分析的处理结果，以及源位置和预定义原因。这些记录是覆盖率元数据，不代表策略语义已验证，也不是运行证据。它们共享现有声明记录预算；即使剩余预算为零，单独的汇总仍保留识别、记录、未记录及各处理结果的数量。分母只涵盖已识别候选项；全部源函数的分母和业务整体完整性仍为 UNKNOWN。

业务 MCP 状态查询区分最后记录的未发布构建与已发布快照。具有 `read_evidence` 权限且来源一致时，以原始选定源快照的记录数为分母报告处理、未处理数量和发布状态。不会推断导致失败的具体输入或所有尝试的历史。记录不存在、无效、读取期间变化和来源不一致均明确标示。仅有策略读取权限时，不检查记录，直接返回 WITHHELD。不会公开其他快照的记录哈希、数量或标识符，也不会把旧来源的业务快照当作新来源的当前结果。


## 部分已知的数值属性

经审核的数值属性可保留已知精度或小数位数，将另一项明确保留为 UNKNOWN。舍入方式、单位和货币分别保留，不会从计算器默认值或数值形式补全未知项。精度与小数位数均已知时，小数位数不得大于精度 (scale <= precision)。这只改善知识描述：具体数值继续使用原有验证规则，小数计算仍要求完整的精度、小数位数和舍入约定。审核通过或 MCP 传递成功不代表运行行为或完整业务语义已被证实。

### 比较顺序与响应状态的有限契约

`Comparator.comparing`、`comparingInt`、`comparingLong`、`comparingDouble`、接收单个提取函数的对应 `thenComparing*` 以及 `reversed()` 使用现有静态 API 契约路径。键 callback 必须对应直接声明、可访问且唯一的非 static、非泛型、非 varargs、零参数源方法，或已支持的 record 访问器。支持形式仅限非绑定 `Type::key` 和输入类型已证明的直接表达式 lambda。static 或绑定引用、重载歧义、继承 getter、块 lambda、未知输入类型及其他 Comparator 重载仍为 UNKNOWN。

可选 revision-1 证据 `Method.callbackDeclaration` 和 `Type.callbackMemberInventory` 将解析后的声明绑定到原有所有者、digest 和范围。选择 callback 前，现有直接成员清单必须完整，并与输出的每个方法记录一致。证据缺失、重复、变化或不可访问时撤销依赖语义。callback 和参数范围使用解码后 Python `str` 中从零开始、末端不包含的字符位置，不是 UTF-8 字节或 Java UTF-16 单元。

primitive 键要求返回类型精确为 `int`、`long` 或 `double`。自然顺序键仅允许规范确认的精确名义类型 `String`、`BigDecimal`、`Instant`、`Integer`、`Long`、`Double`；源代码重定义、子类型和未证明的泛型 Comparable 关系均不适用。自然顺序相等指 `compareTo == 0`，不是 `equals`：BigDecimal 比较忽略 scale，Double 保持规范中的 NaN 和带符号零顺序。键优先级保持不变；`reversed()` 反转已证明接收者中的键方向，后续追加的同值判定键从正向开始。未知连接中断组合，不代入变量或字段初始化表达式。

Spring `ResponseEntity.badRequest()` 和 `notFound()` 保留公开规范常量 400 和 404。`status(int)` 与 `status(HttpStatusCode)` 保留参数指针，值为 UNKNOWN。通过现有隐私处理的有限整数 AST，仅在原有 `java_literal_type` int 证据精确匹配时才可选择 `status(int)`。十进制字符串 wire 值保持原样，不复制到状态 metadata，也不重读原始 token。quoted-literal review 语法不变，此现有数字路径不要求该审查。已掩蔽、不透明、超大、越界、long、floating、伪造或撤销的证据保持 UNKNOWN。直接连接且受支持的 `build()` 保留已证明的状态关系，并声明成功构造时无响应体。单独的 builder 不获得状态。实际 `BodyBuilder` 接收者与声明成员的 `HeadersBuilder` 保持区分，通过有限的规范接收者 bridge 验证。

Java SE 21 与 Spring Framework 6.2.12 是独立的参考规范。实际目标版本、编译、callback 执行、调用选择、排序及 HTTP 传递仍为 UNKNOWN。上限为 16 个顺序键、每片段 16 个 callback 证据记录、每 callback 64 个候选方法及 32 KiB 新增元数据，同时服从现有更严格的预算。不支持或遗漏的输入保留在原始分母中。源 ID、范围、CALLS 和既有 API 项目的规范字节保持不变；新增可选证据或契约字段会改变记录与 sourceSpec digest。现有 enum 和 record 构造证据保持独立。

原始 JSON/MCP、HTML 记录详情及源包 SQLite 保留可选证据。图/RDF 保持其既有声明投影，不创建顺序、状态或 CALLS 边。原始数据可读不等于语义兼容：解释需要识别 revision-1 callback、顺序、响应状态、接收者 bridge 能力，并严格验证 catalog 和源证据。状态诊断共享响应状态能力。旧版或未知消费者必须明确保留 UNKNOWN、拒绝解释或提供标明的原始数据；旧消费者拒绝接收者 bridge 不算解释兼容成功。这不意味着新增 UI、引擎或数据库模式。

`capability`: `java-source-key-callback-1`, `java-comparator-ordering-1`, `spring-response-status-1`, `spring-response-receiver-bridge-1`.

显式方法类型参数必须与现有已证明类型精确一致：primitive factory 要求 `<T>`，自然顺序 `comparing` 要求 `<T,U>`，自然顺序 `thenComparing` 要求 `<U>`。T 是 callback 输入类型，U 是有限 Comparable 键类型。数量错误、未知或不匹配的参数使外层契约保持 UNKNOWN，同时保留独立证明的接收者。primitive 次级键及 `reversed()` 的显式参数不在此有限支持范围内，并不表示 Java 非法。显式 lambda 参数类型使用类型命名空间，同名值参数、局部变量或字段本身不会遮蔽它；`Type::method` 仍拒绝值名称歧义，实际类型 shadow 仍不支持。生产者和交付记录验证器使用同样区分，不新增 generic solver。

显式 T/U 验证还要求可选 Type `callbackTypeNamespace` revision 1：已选直接成员类型、局部/非成员类型和同包顶层类型名称必须关联交付 Type ID、路径、源 digest 及 `/sourceRange` 字符范围。`complete` 要求非 boolean 的精确计数 (`detectedDeclarations = len(declarations) + omittedDeclarations`)、零遗漏和现有完整成员扫描。列表上限为 64，现有 62 个依赖 ID、16 层外部作用域及 32 KiB 契约预算不变。缺失、篡改、重复、不完整、裁剪或超预算证据仅使相关显式契约为 UNKNOWN。本有限扩展不解析局部类型生命周期和调用者/外层类型继承，均保持 UNKNOWN。同名值不阻止类型位置的名称。隐式契约和独立接收者保持不变。Type payload 和证据 digest 会变化，但 source ID、字符范围、CALLS 和现有 catalog entry bytes 不变。现有 MCP/SQLite/HTML reader 保留可选字段；旧消费者的 raw 可读性不是已验证的语义兼容性。

类型列表采用双向验证：每项关联实际 source Type，独立已知的 callback owner、调用者、外层及引用 Type 也必须出现在相关 complete 列表中。同一 Type 承担多个证明角色、依赖 ID 仍在别处存在，不允许从列表中省略它。`known_types` 只接收与现有 lookup 一致的实际交付 Type record；消费者先筛选直接 lexical child 和同包顶层类型，再应用原有 64 条上限。计数相等、ID 并集及自我 digest 不是缺失证明。未观测或超预算证据使显式含义保持 UNKNOWN。内部一致性检查不能替代针对整体协同伪造的可信 source/snapshot provenance；raw 保留与语义认可分开。
