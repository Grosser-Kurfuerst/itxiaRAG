# 文档预处理

本文集中维护原文预处理的调用链、格式适配器、结构策略、输入预算和扩展方式。公共 DTO、存储和查询契约见[首期技术设计](phase1-technical-design.md)，资料获取与准备见[来源接入说明](source-ingestion-plan.md)，验证命令见[项目测试规则](../unit-testing-guidelines.md)。

## 1. 调用链与职责

[PreprocessPipeline](../../ingestion/preprocessing.py) 实现 `DocumentPreprocessor` 协议。原文 API 校验请求和来源权限后，通过 [PreprocessorRegistry](../../ingestion/registry.py) 按 schema/version 选择流水线，最终输出公共 `ProcessedDocument`，复用 [import_processed](../../ingestion/pipeline.py) 的校验、Embedding 和事务保存流程。

```text
RawDocument → ParseStep → StructureStep → ChunkStep → BuildDocumentStep → ValidateStep
阶段：raw      blocks       units          chunked         document          validated
```

每次处理新建 `PreprocessContext`，依次保存原文、内容块、语义父子段和最终文档。构造时检查阶段连接和最终 `validated` 阶段；运行时检查步骤返回类型、实际输出阶段及最终文档，错误直接传播，不生成半成品文档。

| 通用部分 | 可替换部分 |
| --- | --- |
| Pipeline 的执行与阶段检查 | ParseStep 注入 Parser，适配 HTML、Markdown 等格式 |
| 内部 ContentBlock、SemanticContext、SemanticEvidence | StructureStep 注入 StructureStrategy，决定不同类型的父子边界 |
| ChunkStep 的调用接口 | 注入 Chunker，按当前模型预算控制长度 |
| 公共 DTO 构建与校验 | 组合根选择 schema、version 及具体步骤列表 |

内部对象不落表，且不改变现有 ContextDraft/EvidenceDraft 契约。通过 Protocol 和组合实现 Pipeline、Strategy、Adapter 模式；具体组件在[组合根](../../config/components.py) 装配，避免深层继承。

## 2. 格式适配器

格式解析器遵循 `Parser.parse(raw: RawDocument) → list[ContentBlock]`。`ContentBlock` 的 kind/text 表示块类型和文本，level 表示标题级别，ordinal 表示顺序，locator 与 metadata 保留定位和附加信息。后续策略只处理内容块，不依赖 HTML 标签或 Markdown 语法。

[ParserRegistry](../../ingestion/parsers.py) 作为 ParseStep 的 Parser，去除 media_type 的 charset 参数、统一大小写后选择解析器；不支持的格式返回 `UNSUPPORTED_MEDIA_TYPE`。原文按 UTF-8 解码，兼容 BOM，并统一换行符。

| 请求信息 | 作用 |
| --- | --- |
| source.source_type | 来源平台，与 canonical_locator 共同标识来源，不决定解析器或分段规则 |
| raw.media_type | 选择格式解析器 |
| preprocess.schema/version | 选择内容结构对应的预处理流水线 |

| media_type | 当前实现 | 转换规则与定位 |
| --- | --- | --- |
| text/html | HtmlParser | 标准库 HTMLParser 构建轻量节点树；优先微信 js_content，其次 body，再其次解析根；定位为内容块序号 |
| text/markdown | MarkdownParser | 逐行识别块并在空行／类型变化时输出；定位为起止行号 |
| text/plain | 复用 MarkdownParser | 仍会识别 Markdown 标题、列表等标记，没有独立的纯文本解析器 |
| text/x-yuque-markdown | YuqueMarkdownParser | 按行规范化语雀方言，再交给 MarkdownParser；定位仍对应原文起止行号 |

HTML 支持 h1～h6、短的独占粗体栏目与 `【栏目名】`、段落、列表、表格行和 pre 代码；保留 br 换行，忽略脚本与样式。图片保留 alt 说明或缺失说明占位，默认的 alt“图片”视为缺失说明，不下载图片或执行 OCR。

Markdown 支持 ATX 标题、独占行的粗体标题、管道表格、列表与围栏代码，保留正文行尾双空格、代码围栏和缩进。空 ATX 标题忽略；标题中的链接只保留链接文字，正文链接不变。以下图片和引用文本形式是对所有 Markdown 输入（含 `text/plain`）的有意行为变化；重新导入含这些标记的资料时，正文与内容哈希可能改变：

- 独占一行的 Markdown 图片生成 `image` 块，文本为 `[图片：说明]`，缺少 alt 或 alt 为“图片”时为 `[图片：未提供文字说明]`；地址只保留在块 metadata 的 `src`。行内图片替换为同样占位。占位与 HTML 一致，沿用 ParseStep 的图片缺少说明警告。
- 连续 `>` 行生成 `quote` 块，去掉引用前缀并保留块内换行。首行为 GitHub 提示标记时生成 `callout`：NOTE／TIP 以【提示】开头，metadata `level=note`；IMPORTANT 以【注意】开头，`level=note`；WARNING 以【警告】开头，`level=warning`；CAUTION 以【警告】开头，`level=caution`。标记与正文之间保留换行。围栏代码（含引用／提示块内的围栏）中的图片、引用和标题标记原样保留。

`MarkdownParser(pseudo_heading="level2")` 默认把整行加粗视为二级标题，保持既有伪标题行为。`pseudo_heading="nested_label"` 只把不超过 30 字且不含句内标点（，。；！？,;!?）的整行加粗视为标题，级别为最近真实 ATX 标题加一；没有真实标题时为 2，最高为 6，连续伪标题不互相抬升级别。其余整行加粗保留为段落。

[YuqueMarkdownParser](../../ingestion/yuque_markdown.py) 默认使用 `nested_label`，也可注入其他 MarkdownParser。规范化按[语雀方言规则](yuque-ingestion/technical-design.md#42-规范化规则)移除白名单样式标签、删除线（连同只含删除内容的行内代码）和文内锚点链接，将表格行内 `<br>`／`<br/>` 改为“；”、语雀提示块改为 GitHub 提示块、单行折叠块改为 `**标题**：正文`（丢弃其中图片）、独占一行的 HTML 图片改为 Markdown 图片，删除行内空加粗 `****`，空结构改为空行。白名单外尖括号（如 `<你的用户名>`）保留；围栏代码中的内容不做方言改写。每行只改写为一行或空行，保持原文行号。

例如微信原文：

```html
<div id="js_content">
  <p><strong>【优缺点】</strong></p>
  <p>优点：安静<br>缺点：贵</p>
</div>
```

解析后是二级 heading `【优缺点】` 和 paragraph `优点：安静\n缺点：贵`。此时还没有决定父段或最终 Evidence。正文以解析后的文本为准，HTML 定位不代表原 HTML 的字符偏移。

## 3. 内容结构策略

[结构策略](../../ingestion/strategies.py) 遵循 `StructureStrategy.build(blocks, raw) → list[SemanticContext]`，注入 StructureStep 后生成语义父段及其 SemanticEvidence。目前采用标题层级、栏目名称与显式边界规则，不调用模型判断语义。评测的子块只作为召回入口，按自然段合并而不解析小节语义；购买指南和经验文档仍按小节形成子块；教程使用[章节树策略](../../ingestion/sections.py)。

| 策略 | 父段 | 子块 |
| --- | --- | --- |
| ReviewStrategy | 单机评测一台笔记本一个父段，须提供 `entity_title`；多机型由 `raw.metadata.entity_headings` 显式指定标题边界 | 按原文顺序合并自然段形成的检索块，见下文“评测检索块” |
| PurchaseGuideStrategy | 全局建议、预算说明、单个推荐卡和 FAQ 分开 | 推荐卡中的配置、理由、限制等小节 |
| ExperienceCaseStrategy | 默认二级标题作为章节/案例；构造参数 section_level 可调整 | 案例内现象、检查、处理、结果等小节 |
| SectionedDocumentStrategy(TUTORIAL) | 按章节树自适应选择顶层，超长时按下一级标题下钻，短父段只在同一上级下相邻合并 | 所有标题开启新块，自然段按目标长度合并，保留步骤与提示的相连关系 |

多机型评测示例：`entity_headings=["Laptop A", "Laptop B"]`，这些标题必须出现在解析后的标题块中，缺失时明确报错。单机评测必须传 `entity_title` 作为父段标题，缺失或为空返回 ENTITY_TITLE_REQUIRED，不退回文章标题；父段标题会拼入每个子块的检索文本，让“这台电脑”等指代带上机型名。可另传 `entity_key` 指定稳定身份。购买指南保留推荐卡所属 budget 元数据，并保留原文中的全局价格警告。以上三种策略把首个一级标题作为文档标题，不额外生成只有标题的父段。

购买指南支持 `## 5000～6000元 → ### 机型 → #### 配置/购买建议` 的层级，也支持独占粗体标题。识别到价格警告、全局建议、本期改动时，把相关原文附到各推荐卡的 global_guidance 元数据；卡片带时效提醒，检索返回卡片时仍能读到全局限制。不能把任意视觉排版当作可靠语义标记，来源没有清晰标题时应在采集侧补充边界或替换策略。

预算标题必须是二级或更浅标题，并完整符合预算区间格式；机型卡标题中的价格不会覆盖所属预算。即使未出现预算标题，推荐卡仍继承全局限制与时效提醒。购买建议、推荐理由等受保护小节连同其下级标题整体形成一个 Evidence。

### 评测检索块

评测检索命中任一子块都返回整台电脑的父段，因此子块只负责召回，不承担语义完整性。[ReviewStrategy](../../ingestion/strategies.py) 按以下规则合并内容块。长度按块文本的字符数（含段落间隔）计算，目标长度默认 400 字符（`target_chars`）；短于 120 字符（`min_chars`）的块并回前一块，过短的首块并入后一块，合并后不超过 `target_chars + min_chars`。短栏目同样参与合并，因此“优点！”这类短栏目可能与前文同块：

- 以自然段为基本单位，按原文顺序合并相邻段落，加入下一段会超过目标长度时结束当前块；超出模型预算的块交给 BudgetChunker 按段落／句子拆分。
- 栏目名开启新块：`【栏目名】`，以及不含“，。；”且不超过 30 字的标题块（如 `## 散热分析`、粗体 `优点！`）。整句加粗的数据或结论不作为断点；比当前栏目更深的子标题（如散热分析下的测试结果）按普通段落处理。
- 紧跟“优点”的“缺点”（以及紧跟“优势”的“劣势”）不另起块，优缺点留在同一块。
- 不超过 20 字、以“：”结尾的短引导句（如“它的配置如下：”“它的优缺点如下：”）开启新块，使开场、配置与优缺点分开；散热分析、购买建议等测试类栏目内的引导句不断块。
- 栏目名、以“：”结尾的引导句、以“；”结尾的并列数据与下一段相连；连续列表项、表格行和 `1，` `2，` 形式的编号段落留在同一块。
- 只含一个或多个“[图片：未提供文字说明]”的段落不进入父段和子块，文档警告仍保留；有说明文字的图片和夹在正文中的占位照常保留。

这些规则尽量让测试条件与结果、引导句与内容留在同一块，但不保证；评测子块不标记 atomic，超预算时拆分而不拒绝导入。

父段及购买指南、经验文档的子块 key 基于标题和同名标题的出现次数；边界和标题不变时，普通正文修改不改变这些 key。评测子块 key 按块序号生成（`evidence-chunk-N`），正文增删可能移动后续块边界；重新导入时同序号子块沿用原 ID，但内容和向量可能改变，多出的序号新建、缺席的序号删除，父段 key 和 ID 不受影响。重复同名章节前插入同名标题可能改变后续次数；预算切分产生的子块还带 part 序号，切分数量变化可能改变最终子块 key。来源应尽量提供可区分的标题，并固定处理策略与预算。

购买指南和经验文档的 Evidence 按小节分组，散热条件/结果、购买建议等受保护小节，以及含表格或代码的整个小节，标为 `atomic` 不可拆单元。受保护栏目还包含其下级标题，后续长度控制保留完整内容或明确拒绝超限。

### 教程章节树与检索块

`tutorial@1` 使用 `SectionedDocumentStrategy(TUTORIAL)`。参数为父段上限 3000 字、短父段阈值 150 字、子块目标 500 字、短子块阈值 120 字。父段规划长度按去空白的正文字符数计算，不计标题；子块合并长度包含标题、正文及段落间隔。它与来源平台、输入格式独立，不修改其他三种策略。

- 按标题级别建立任意深度的章节树，级别跳跃按相对深度挂载。文档标题来自 `raw.metadata.title`，正文第一个 H1 也按普通章节处理。虚拟根收纳第一个标题前的导语；无标题文档整篇一个父段，导语和无标题文档的父段标题均为文档标题。
- 根只有一个子节点、根导语短于 150 字且该节点还有子节点时，去掉包裹标题，把其导语并入根导语，并以其子节点为顶层；重复判断。包裹标题不进入父段路径。
- 顶层子树不超过 3000 字或没有子标题时，整棵子树成为一个父段。否则章节导语非空时单独成父段，再对子节点递归。没有子标题的超长章节仍保留一个完整父段。
- 短于 150 字的父段只合并到同一上级下相邻的前一个父段；没有前一个时并入后一个；没有同级邻居时保留。合并保持原文顺序，沿用接收方标题和 key，不跨上级合并。
- 父段标题为章节路径，如“安装篇 > 三、开始安装”。超过 200 字时保留前 99 字和后 100 字，中间用“…”连接。key 用完整路径哈希，同名路径按出现次数区分，不受显示标题截断影响。父段 metadata 保留完整 `section_path`、`content_type=tutorial` 和 `omitted_images`。
- 无说明图片在建树前移除占位（含 Markdown 行内图片及 HTML 图文混排），仅整理含占位行的多余空白；其他行原样保留，包括代码与列表缩进、连续空格和行尾空白，块内换行保留。移除后仅剩空白的块整体过滤；数量按原文父段区间中移除的占位数写入 `omitted_images`，有说明图片保留占位文字。图片过滤不重新编号原文块，父段 locator 保留连续的 `block_start/end`，Markdown 输入另保留 `line_start/end`。区间包含被过滤的图片，便于计数与警告归属。
- 父段内任意标题（含伪标题）开启新子块，标题与后文相连。连续标题尚无正文时按原文顺序带入后续块，key 与 `section` 取最后一个标题，定位覆盖这些标题。以“：”“；”结尾的引导句、连续列表／表格行、`1、` `2、` 式编号段落沿用相连规则；`callout` 与前一块相连，警告尽量留在所属步骤。短于 120 字的子块并入前一块。
- 子块 key 为小节标题哈希加小节内块序号，同名小节用出现次数区分；普通正文修改或另一小节的块数变化不移动该小节的序号。短块合并沿用接收块的 key；预算拆分另加 `-part-N`。

表格整体参与合并，代码在合并阶段不切开，教程子块均不标 `atomic`；超预算交给 BudgetChunker。当前教程不做表格行组策略，也没有知识、工具条目流水线。

## 4. Evidence 输入预算

[BudgetChunker](../../ingestion/chunking.py) 在 Embedding 之前检查完整编码文本 `父段标题 + 换行 + Evidence.body`；带 retrieval_prefix 的子块为 `父段标题 + 换行 + 前缀 + 换行 + Evidence.body`。默认 `Utf8ByteCounter` 与 2400 字节预算，不把字符/字节当精确 token，也不自动加载或下载模型。适配目标模型时，在组合根注入 `TokenizerCounter(tokenizer.encode)` 和模型允许的 max_input_units；encode 应包含特殊 token，预算应留出模型要求的余量。字节预算需要按实际服务校准，不能对任意 tokenizer 承诺模型 token 上限。

普通长 Evidence 按剩余长度均分为所需的最少块数：每次以均分长度为目标，在预算可容纳的范围内选最接近目标的断点，优先段落、句子边界，其次换行，都没有时按 Unicode 字符边界切分；早于目标长度一半的断点不采用，避免只含“配置”标题或末句的极短子块。父段正文保持完整，拆出的多个 Evidence 平级保存。

连续的 `| … |` 行视为管道表格，第一行（及紧随的 `| --- |` 分隔行）是表头，表格只在行之间断开，单元格中的句号不作为断点。从数据行开始的子块把表头写入 `retrieval_prefix`，只进入编码文本和关键词检索文本，body 与定位仍是原始数据行；表头加一整行数据仍超预算时不附表头。子块 locator 的 parent_char_start/end 是父段正文中的字符偏移，end 为开区间，便于精确引用。小于预算的子块不变更正文/key。

教程的目录／文档检索前缀参与同一预算检查，拆分时每个子块保留前缀，表格数据行的表头追加在它之后。代码超预算时可沿换行拆分，父段正文仍完整保留。

购买指南、经验文档中的不可拆分小节超限返回 SEMANTIC_UNIT_TOO_LARGE，不静默截断测试条件、表头或代码。可以调整部署预算或自定义更细且完整的结构策略。拆分同时遵守 32000 字符、每父段 100 子块、整篇 1000 子块的公共约束；ValidateStep 可注入 chunker.validate，在 DTO 构建后再次验证最终模型输入。

每个最终 Evidence 对应一个向量。Embedding 适配器中的批处理只是一次请求发送多条输入，不会继续拆分单条输入。标准化 JSON 入口跳过该预算切分流程，调用方仍负责准备满足模型预算的 Evidence。

## 5. 扩展与步骤编排

| 要扩展的能力 | 实现与接入位置 |
| --- | --- |
| 新输入格式 | 实现 Parser.parse，在 ParserRegistry.register(media_type, parser) 注册，并将该注册表注入 ParseStep |
| 替换已有格式 | 构造 ParserRegistry(parsers=完整映射)；该映射替代默认映射，不自动合并，重复 register 会报错 |
| 新文章类型 | 实现 StructureStrategy.build，组装流水线并在 PreprocessorRegistry 注册新的 schema/version；BuildDocumentStep 输出的 schema/version 须匹配注册项 |
| 新长度策略 | 实现 Chunker.chunk 并注入 ChunkStep；默认 BudgetChunker 也可仅替换 InputCounter.count |
| 新处理步骤 | 实现 PreprocessStep.process(context)，声明 input_stage/output_stage，在组合根的有序步骤列表中插入 |

步骤可以增删或调整顺序，但须遵守阶段依赖。例如新增两个 `blocks → blocks` 步骤后，可以采用：

```text
ParseStep → CleanBlocksStep → AnnotateBlocksStep → StructureStep → 后续步骤
ParseStep → AnnotateBlocksStep → CleanBlocksStep → StructureStep → 后续步骤
```

CleanBlocksStep 和 AnnotateBlocksStep 是扩展示意名称，当前没有内置这两个步骤。它们可互换的前提是自身业务语义也允许调序；解析应先于结构划分，长度控制应使用已形成的父子段，校验应在文档构建之后。现有阶段为 raw/blocks/units/chunked/document/validated，新增步骤通常复用已有阶段。

结构策略与解析器主要使用 Protocol 和组合，具体类实现对应方法即可，不要求继承协议类。ExperienceCaseStrategy 继承通用 HeadingSectionsStrategy 复用章节划分。步骤属于受信任应用代码，不接受 HTTP 请求指定顺序、加载 Python 路径或执行自定义代码。

### 教程增强步骤

[组合根](../../config/components.py) 的 `pipeline(schema, strategy, enrich=(), *, image_warning=None)` 在 StructureStep 和 ChunkStep 之间插入 `units → units` 步骤；其他三种 schema 不插入增强步骤。`tutorial@1` 的顺序为：

```text
Parse → Structure(Sectioned[TUTORIAL]) → CalloutWarning → TimeExpression → RetrievalPrefix → Chunk → Build → Validate
```

| 步骤 | 当前行为 |
| --- | --- |
| [CalloutWarningStep](../../ingestion/enrichment.py) | 原文 `level=warning/caution` 的 callout 按父段 `block_start/end` 写入父段 warnings；第一个标题前的提示写入文档 warnings，无标题时也作为全文提示。保留【警告】标记，单条截断 300 字并去重；普通 note 不作为风险警告 |
| TimeExpressionStep | 识别“目前（2022年初）”“截至 2023 年”“（2025.11 更新）”等明确年份表述，每父段只取第一处，提示“含时间限定表述‘…’，请结合来源日期判断是否仍适用” |
| RetrievalPrefixStep | 由 `collection_path` 与文档标题生成“目录路径 > 文档标题”，略去与完整父段章节路径重复的部分；与已有前缀（如表头）以换行组合，不改正文和定位 |

全局风险提示需要写入 `PreprocessContext.warnings`，因此作为步骤而非章节策略的一部分；导语被短段规则合并后仍按原文第一个标题的位置判断。BuildDocumentStep 合并 `raw.metadata.warnings` 与处理中的文档 warnings。

`ParseStep(parser, image_warning=...)` 可配置图片警告文案。注册流水线时显式传入 `image_warning`，为 `None` 时使用 ParseStep 默认文案。教程使用“原文含未转写的截图，操作界面以原文链接为准”，其他流水线仍为“原文含未提供文字说明的图片，关键参数需人工补录。”。增强步骤不调用模型，也不计算来源距今多久。

## 6. 原文导入 API

`POST /api/v1/sources/raw/` 需要 Token 和 maintain_source，写入 internal 还需要 read_internal。请求仅提交文本和元数据，不传 URL 抓取命令或本机路径：

```json
{
  "source": {"source_type": "wechat", "canonical_locator": "synthetic:review", "visibility": "public"},
  "preprocess": {"schema": "product_review", "version": 1},
  "raw": {
    "content": "# Laptop A\n\n## 配置\n\n16GB 内存。\n\n## 购买建议\n\n适合轻办公，不适合大型游戏。",
    "media_type": "text/markdown",
    "metadata": {"title": "合成评测", "entity_title": "Laptop A", "source_date": "2026-09-28", "author": "合成作者"}
  }
}
```

默认注册 `product_review@1`、`purchase_guide@1`、`experience_case@1`、`tutorial@1`，四者均支持 text/html、text/markdown、text/plain、text/x-yuque-markdown。平台和 Schema 独立，例如语雀 Markdown 同样可以选择购买指南策略。media_type 可带 charset 参数，但内容必须 UTF-8。HTTP JSON 总大小仍限 2 MiB。

metadata 的 title/source_date/entity_title/entity_key/entity_headings/collection_path/document_metadata/warnings 是通用控制字段，API 校验它们的格式。`collection_path` 是可选字符串数组，最多 10 项，每项不超过 100 字；可传空数组，项须为非空文本。它表示来源内的目录，不限于语雀。校验后的值进入 RawDocument.metadata，增强步骤可读，并保留在文档 metadata 中；缺省不新增该字段。其余字段保留给来源或新增步骤，并写入文档 metadata；document_metadata 可显式补充文档元数据。未知日期留空，不使用导入日期。HTTP 不指定步骤顺序，步骤/策略在 config/components.py 的有序列表中配置；新增类型由显式 register 接入，不读取任何请求提供的 Python 路径。

导入教程时将 `preprocess` 设为 `{"schema": "tutorial", "version": 1}`，在 `raw.metadata` 提供文档标题，可附 `"collection_path": ["合成目录"]`；语雀 Markdown 的 `media_type` 为 `text/x-yuque-markdown`。合成原文 API 样本及检索预期见[教程流水线验收](yuque-ingestion/implementation-phases.md#33-验收)。当前入口仍为逐篇原文 API，没有语雀读取客户端、导入清单或批量导入命令。

权限与来源范围校验在解析之前执行，原文和公共 DTO 校验在创建模型适配器之前完成；解析失败不调用 Embedding 或保存。成功响应与标准导入一致 `{source_id, context_ids, reused}`。Python 调用方可用 import_raw；HTTP 先调用 preprocess_raw，再调用 import_processed，以便模型未配置时仍准确报告预处理输入错误。

PREPROCESS_MAX_INPUT_BYTES 默认为 2400，可在环境或 Compose 中调整。使用目标 tokenizer 时，在组合根构造 `preprocessors(counter=TokenizerCounter(encode), max_input_units=模型预算)`。此时 max_input_units 的单位为该 tokenizer 的 token 数，与字节环境变量区分；仅修改环境变量不会自动启用 tokenizer。

## 7. 验收与限制

单测覆盖步骤增删/调序、阶段错误、HTML/Markdown 保真、单/多机型边界、评测检索块合并规则、推荐卡预算与全局限制、经验案例、教程章节规划与增强步骤、collection_path、稳定 key、全文覆盖和长度控制；集成测试覆盖真实 Token API、四类文档导入/检索、更新复用、权限与失败保留已有文档。教程用合成 Markdown 检查章节路径、风险与时效警告、重复复用及 internal 可见性。专项与全量命令见[项目测试规则](../unit-testing-guidelines.md)，真实服务操作见[部署与运行验收](deployment.md)。

当前不抓取平台、不下载图片、不执行 OCR、不自动识别文档类型，不调用 LLM 划分父子边界。HTML 的视觉格式与微信历史模板仍需用获准真实样本验证；图片缺失说明会生成文档警告。真实 tokenizer/模型输入上限与检索效果需要部署侧校准。标准化 JSON API 的调用方仍负责其 Evidence 长度，新增预处理只对原文入口生效。
