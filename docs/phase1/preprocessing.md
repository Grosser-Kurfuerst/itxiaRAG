# 文档预处理

## 流水线与扩展点

`ingestion/preprocessing.py` 实现 `DocumentPreprocessor` 协议的顺序流水线，最终输出公共 `ProcessedDocument`，复用导入校验与保存流程。

```text
RawDocument → ParseStep → StructureStep → ChunkStep → BuildDocumentStep → ValidateStep
阶段：raw      blocks       units          chunked         document          validated
```

流程由有序步骤列表配置。新增能力实现 `PreprocessStep.process(context)` 并声明 `input_stage/output_stage`；兼容阶段的步骤可以增删、调序。例如两个 `blocks → blocks` 的清洗步骤可自由调整先后顺序，结构划分必须在解析之后，校验必须在构建之后。不允许 HTTP 请求加载 Python 路径或自行指定代码。

构造时检查阶段连接和最终 `validated` 阶段；运行时检查步骤返回类型、实际输出阶段及最终文档，错误直接传播，不生成半成品文档。步骤由应用代码显式注册，不构成不可信代码沙箱。

| 通用部分 | 可替换部分 |
| --- | --- |
| Pipeline 的执行与阶段检查 | ParseStep 注入 Parser，适配 HTML、Markdown 等格式 |
| 内部 ContentBlock、SemanticContext、SemanticEvidence | StructureStep 注入 StructureStrategy，决定不同类型的父子边界 |
| ChunkStep 的调用接口 | 注入 Chunker，按当前模型预算控制长度 |
| 公共 DTO 构建与校验 | 组合根选择 schema、version 及具体步骤列表 |

内部对象不落表，且不改变现有 ContextDraft/EvidenceDraft 契约。通过 Protocol 和组合实现 Pipeline、Strategy、Adapter 模式，避免深层继承。

## 实施状态

已实现通用流水线、步骤协议、内存对象与公共 DTO 构建/校验、HTML/Markdown/纯文本解析器，以及三类结构策略；模型预算控制和原文 API 在后续功能提交中接入。当前标准化 JSON API 行为保持不变。

`ingestion/parsers.py` 的 ParserRegistry 可直接注入 ParseStep，按媒体类型选择适配器。HTML 优先提取微信 `js_content`；其他 HTML 读取 body。支持 h1～h6、独占段落的粗体栏目、表格、列表与代码。Markdown 支持 ATX 标题、独占行的粗体标题、管道表格、列表与围栏代码，并保留正文有意义空格。图片保留说明或缺失说明占位，不下载图片或执行 OCR。原文定位为解析块序号或 Markdown 行号，正文以解析后的文本为准。

## 内容类型策略

`ingestion/strategies.py` 提供以下策略，均可注入 StructureStep，平台与类型互相独立。

| 策略 | 父段 | 子块 |
| --- | --- | --- |
| ReviewStrategy | 默认一台笔记本一个父段；多机型由 `raw.metadata.entity_headings` 显式指定标题边界 | 配置、优缺点、散热、购买建议等小节 |
| PurchaseGuideStrategy | 全局建议、预算说明、单个推荐卡和 FAQ 分开 | 推荐卡中的配置、理由、限制等小节 |
| ExperienceCaseStrategy | 默认二级标题作为章节/案例；构造参数 section_level 可调整 | 案例内现象、检查、处理、结果等小节 |

多机型评测示例：`entity_headings=["Laptop A", "Laptop B"]`，这些标题必须出现在解析后的内容块中，缺失时明确报错。默认单机评测可传 `entity_title/entity_key` 指定机型标题及稳定身份。购买指南保留推荐卡所属 budget 元数据，并保留原文中的全局价格警告。首个一级标题用于文档标题，不额外生成只有标题的父段。

key 基于标题和同名标题的出现次数，正文更新不改变 key；重复同名章节前插入同名标题可能改变后续次数，来源应尽量提供可区分的标题。Evidence 按小节分组，散热条件/结果、购买建议、表格、代码标为不可拆分语义单元，后续长度控制应保留它们或明确拒绝超限，不能静默截断。测试使用合成资料，不提交真实文章或维修记录。
