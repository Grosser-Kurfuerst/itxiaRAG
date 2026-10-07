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

已实现通用流水线、步骤协议、内存对象与公共 DTO 构建/校验、HTML/Markdown/纯文本解析器、三类结构策略和输入预算控制，并接入原文导入 API。现有标准化 JSON API 行为保持不变。

`ingestion/parsers.py` 的 ParserRegistry 可直接注入 ParseStep，按媒体类型选择适配器。HTML 优先提取微信 `js_content`；其他 HTML 读取 body。支持 h1～h6、独占段落的粗体栏目、表格、列表与代码。Markdown 支持 ATX 标题、独占行的粗体标题、管道表格、列表与围栏代码，并保留正文有意义空格。图片保留说明或缺失说明占位，不下载图片或执行 OCR。原文定位为解析块序号或 Markdown 行号，正文以解析后的文本为准。

## 内容类型策略

`ingestion/strategies.py` 提供以下策略，均可注入 StructureStep，平台与类型互相独立。

| 策略 | 父段 | 子块 |
| --- | --- | --- |
| ReviewStrategy | 默认一台笔记本一个父段；多机型由 `raw.metadata.entity_headings` 显式指定标题边界 | 配置、优缺点、散热、购买建议等小节 |
| PurchaseGuideStrategy | 全局建议、预算说明、单个推荐卡和 FAQ 分开 | 推荐卡中的配置、理由、限制等小节 |
| ExperienceCaseStrategy | 默认二级标题作为章节/案例；构造参数 section_level 可调整 | 案例内现象、检查、处理、结果等小节 |

多机型评测示例：`entity_headings=["Laptop A", "Laptop B"]`，这些标题必须出现在解析后的内容块中，缺失时明确报错。默认单机评测可传 `entity_title/entity_key` 指定机型标题及稳定身份。购买指南保留推荐卡所属 budget 元数据，并保留原文中的全局价格警告。首个一级标题用于文档标题，不额外生成只有标题的父段。

购买指南支持 `## 5000～6000元 → ### 机型 → #### 配置/购买建议` 的层级，也支持独占粗体标题。识别到价格警告、全局建议、本期改动时，把相关原文附到各推荐卡的 global_guidance 元数据；卡片带时效提醒，检索返回卡片时仍能读到全局限制。不能把任意视觉排版当作可靠语义标记，来源没有清晰标题时应在采集侧补充边界或替换策略。

预算标题必须是二级或更浅标题，并完整符合预算区间格式；机型卡标题中的价格不会覆盖所属预算。即使未出现预算标题，推荐卡仍继承全局限制与时效提醒。散热/购买建议等受保护小节连同其下级标题整体形成一个 Evidence，测试条件与结果不会因为三级标题而分离。

key 基于标题和同名标题的出现次数，正文更新不改变 key；重复同名章节前插入同名标题可能改变后续次数，来源应尽量提供可区分的标题。Evidence 按小节分组，散热条件/结果、购买建议、表格、代码标为不可拆分语义单元，后续长度控制应保留它们或明确拒绝超限，不能静默截断。测试使用合成资料，不提交真实文章或维修记录。

## 输入预算

`BudgetChunker` 检查完整编码文本 `父段标题 + 换行 + Evidence.body`。默认 `Utf8ByteCounter` 与 2400 字节预算，不把字符/字节当精确 token，也不自动加载或下载模型。适配目标模型时，在组合根注入 `TokenizerCounter(tokenizer.encode)` 和模型允许的 max_input_units；encode 应包含特殊 token，预算应留出模型要求的余量。字节预算需要按实际服务校准，不能对任意 tokenizer 承诺模型 token 上限。

普通长 Evidence 优先按段落、句子边界拆分，单句过长再按 Unicode 字符边界拆分；父段正文保持完整，拆出的多个 Evidence 平级保存。子块 locator 的 parent_char_start/end 是父段正文中的字符偏移，end 为开区间，便于精确引用。小于预算的子块不变更正文/key。

不可拆分小节超限返回 SEMANTIC_UNIT_TOO_LARGE，不静默截断测试条件、表头或代码。可以调整部署预算或自定义更细且完整的结构策略。拆分同时遵守 32000 字符、每父段 100 子块、整篇 1000 子块的公共约束；ValidateStep 可注入 chunker.validate，在 DTO 构建后再次验证最终模型输入。

## 原文导入 API

`POST /api/v1/sources/raw/` 需要 Token 和 maintain_source，写入 internal 还需要 read_internal。请求仅提交文本和元数据，不传 URL 抓取命令或本机路径：

```json
{
  "source": {"source_type": "wechat", "canonical_locator": "synthetic:review", "visibility": "public"},
  "preprocess": {"schema": "product_review", "version": 1},
  "raw": {
    "content": "# Laptop A\n\n## 配置\n\n16GB 内存。\n\n## 购买建议\n\n适合轻办公，不适合大型游戏。",
    "media_type": "text/markdown",
    "metadata": {"title": "合成评测", "source_date": "2026-09-28", "author": "合成作者"}
  }
}
```

默认注册 `product_review@1`、`purchase_guide@1`、`experience_case@1`，三者均支持 text/html、text/markdown、text/plain。平台和 Schema 独立，例如语雀 Markdown 同样可以选择购买指南策略。media_type 可带 charset 参数，但内容必须 UTF-8。HTTP JSON 总大小仍限 2 MiB。

metadata 的 title/source_date/entity_title/entity_key/entity_headings/document_metadata/warnings 是通用控制字段，API 校验它们的格式。其余字段保留给来源或新增步骤，并写入文档 metadata；document_metadata 可显式补充文档元数据。未知日期留空，不使用导入日期。HTTP 不指定步骤顺序，步骤/策略在 config/components.py 的有序列表中配置；新增类型由显式 register 接入，不读取任何请求提供的 Python 路径。

权限与来源范围校验在解析之前执行，原文和公共 DTO 校验在创建模型适配器之前完成；解析失败不调用 Embedding 或保存。成功响应与标准导入一致 `{source_id, context_ids, reused}`。Python 调用方可用 import_raw；HTTP 先调用 preprocess_raw，再调用 import_processed，以便模型未配置时仍准确报告预处理输入错误。

PREPROCESS_MAX_INPUT_BYTES 默认为 2400，可在环境或 Compose 中调整。使用目标 tokenizer 时，在组合根构造 `preprocessors(counter=TokenizerCounter(encode), max_input_units=模型预算)`。此时 max_input_units 的单位为该 tokenizer 的 token 数，与字节环境变量区分。

## 验收与限制

单测覆盖步骤增删/调序、阶段错误、HTML/Markdown 保真、单/多机型边界、推荐卡预算与全局限制、经验案例、稳定 key、全文覆盖和长度控制；集成测试覆盖真实 Token API、三类文档导入/检索、更新复用、权限与失败保留已有文档。

当前不抓取平台、不下载图片、不执行 OCR、不自动识别文档类型，不调用 LLM 划分父子边界。HTML 的视觉格式与微信历史模板仍需用获准真实样本验证；图片缺失说明会生成文档警告。真实 tokenizer/模型输入上限与检索效果需要部署侧校准。标准化 JSON API 的调用方仍负责其 Evidence 长度，新增预处理只对原文入口生效。
