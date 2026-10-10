# 第一批技术方案：教程、工具条目与知识的预处理和导入

本文给出满足[需求分析](requirements-analysis.md)的技术方案，覆盖操作教程（`tutorial`）、工具条目（`tool_card`）、知识科普／对比／速查（`knowledge`）三类语雀文档。现有原文预处理契约见[文档预处理](../preprocessing.md)，公共 DTO 与存储见[首期技术设计](../phase1-technical-design.md)。**阶段 1～3 已实现；阶段 4 代码已实现，需 Token 的接口实测与真实教程验收待补；知识与工具流水线仍为方案，阶段 5、6 未开始。**

## 1. 设计目标与原则

- **复用现有主链**：原文 API、[PreprocessorRegistry](../../../ingestion/registry.py)、[PreprocessPipeline](../../../ingestion/preprocessing.py)、[BudgetChunker](../../../ingestion/chunking.py)、[import_raw／preprocess_raw](../../../ingestion/pipeline.py)、存储与检索都不改接口，现有三种 schema 的策略也不改。
- **平台、格式、内容三者分离**，与现有约定“source_type 不决定解析器或分段规则”一致：

  | 维度 | 标识 | 负责方 |
  | --- | --- | --- |
  | 平台 | `source_type=yuque` | `sources/yuque`：读取客户端、连接器（身份、链接、标题清洗、平台元数据）、导入清单 |
  | 格式方言 | `media_type=text/x-yuque-markdown` | `ingestion` 中的语雀 Markdown 解析器 |
  | 内容结构 | `schema=tutorial/tool_card/knowledge` | `ingestion` 中的章节策略与增强步骤 |

- **一个策略，三套参数**：三类文档的差异集中在 SectionProfile 参数和少量增强步骤。教程与知识互相误判时只影响参数，不会产生错误结构。
- **类别以人工清单为准**：只有清单中的单篇条目和目录规则能决定类别，未登记的文档不导入。
- **只在已确认的变化点上抽象**：
  - 保留的抽象：读取客户端（OpenAPI／本地快照两种实现）、方言解析器、SectionProfile、增强步骤、schema 注册。
  - 不做的事：API 侧自动识别类别、可插拔的分类规则链、跨平台的通用分类框架、任务队列、同步状态表、删除流程。第二个平台或第二种需求真正出现时再抽取。

## 2. 总体架构

### 2.1 数据流

```text
语雀（官方 OpenAPI，或本地快照）
  → YuqueConnector.list：经 YuqueClient 列出文档，映射为 SourceRef                     [sources/yuque]
  → Manifest.classify：单篇条目 → 目录规则；未登记不导入                              [sources/manifest.py，通用]
  → YUQUE_CATEGORY_PIPELINES：tutorial→tutorial@1，tool_card→tool_card@1，knowledge→knowledge@1   [组合根]
  → YuqueConnector.fetch：读取 Markdown，生成身份、链接、清洗后标题与平台元数据         [sources/yuque]
  → build_request：合并清单元数据补丁与可见性，组装原文导入请求                         [sources/importing.py，通用]
  → preprocess_raw：权限与来源校验                                                   [ingestion.pipeline，已有]
  → PreprocessorRegistry.process(raw, schema, version)：按 schema 选择流水线          [已有]
      ParseStep(YuqueMarkdownParser)                                                [新解析器]
      → StructureStep(SectionedDocumentStrategy(profile))                           [新策略]
      → 增强步骤：风险提示／时效表述／工具身份／来源日期／检索前缀                     [新步骤]
      → ChunkStep(BudgetChunker) → BuildDocumentStep → ValidateStep                [已有]
  → import_processed：Embedding → 事务保存                                          [已有]
```

### 2.2 模块与文件

| 位置 | 新增或修改 | 职责 |
| --- | --- | --- |
| [ingestion/parsers.py](../../../ingestion/parsers.py) | 修改 | MarkdownParser 通用增强：图片块、引用与提示块、空标题、伪标题参数（默认行为不变） |
| `ingestion/yuque_markdown.py` | 新增 | 语雀方言行规则与 YuqueMarkdownParser |
| `ingestion/sections.py` | 新增 | SectionProfile、SectionNode，建树、父段规划、子块合并函数，SectionedDocumentStrategy、ToolCardStrategy |
| `ingestion/enrichment.py` | 新增 | CalloutWarningStep、TimeExpressionStep、ToolIdentityStep、SourceDateNoticeStep、RetrievalPrefixStep |
| [ingestion/preprocessing.py](../../../ingestion/preprocessing.py) | 修改 | ParseStep 的图片警告文案可配置，默认不变 |
| [config/components.py](../../../config/components.py) | 修改 | 注册语雀媒体类型、三条流水线与类别映射 |
| [contracts/serializers.py](../../../contracts/serializers.py) | 修改 | RawMetadataSerializer 增加通用字段 `collection_path` |
| [sources/yuque/client.py](../../../sources/yuque/client.py) | 新增 | YuqueDocRef、YuqueClient 协议、OpenAPI 与快照两种实现 |
| [sources/yuque/connector.py](../../../sources/yuque/connector.py) | 新增 | 语雀类别集合、标题清洗、YuqueConnector（实现通用 SourceConnector） |
| [sources/manifest.py](../../../sources/manifest.py) | 新增（通用） | 清单读取与校验（标准库 tomllib）、`classify`，各平台共用 |
| [sources/importing.py](../../../sources/importing.py) | 新增（通用） | `build_request`、SourceImportService、导入报告，各平台共用 |
| [sources/commands.py](../../../sources/commands.py) | 新增（通用） | 来源导入命令基类：清单、账号、试运行、提交与报告 |
| [sources/management/commands/import_yuque.py](../../../sources/management/commands/import_yuque.py) | 新增 | 命令行入口，只负责语雀参数与连接器装配 |
| [sources/yuque/manifests/itxia.toml](../../../sources/yuque/manifests/itxia.toml) | 新增 | itxia 团队导入清单，只含文档标识、类别、跳过原因和可见性 |

`sources` 作为无模型的 Django 应用加入 `INSTALLED_APPS`，只为提供管理命令。

### 2.3 依赖方向

```text
sources.management（组合） → sources.commands、sources.yuque → sources.importing、sources.manifest → ingestion.pipeline、contracts
config.components → ingestion.*（解析器、章节策略、增强步骤）
ingestion 不依赖 sources；sources 导入经 preprocess_raw 与 import_processed，不直接操作 ORM 或模型服务
```

语雀方言解析器放在 `ingestion`，因为它是格式适配器，与 HtmlParser 优先读取微信 `js_content` 的做法一致。读取接口、身份与标题清洗是平台知识，留在 `sources/yuque`；清单、导入服务和命令基类与平台无关，放在 `sources` 公共模块。

语雀通过 [YuqueConnector](../../../sources/yuque/connector.py) 实现通用 [SourceConnector](../../../contracts/types.py) 协议（`list() → SourceRef`、`fetch(ref) → FetchedSource`），协议与公共模块见[来源连接器改造方案](../source-connector-design.md)。

## 3. 运行时类别选择

### 3.1 类别与流程

- **类别**（category）是业务事实，回答“这篇文档是什么”，由清单决定。
- **流程**（schema@version）是技术实现，回答“用哪条流水线处理”，由组合根中的映射表决定。
- 两者通过一张映射表连接。升级某类处理方式时，注册 `tutorial@2` 并修改映射，清单不变。映射表中没有的类别视为“未接入”，不导入，因此清单里不再单独维护启用列表。

```python
# 组合根：类别 → 流程。清单只写类别，流程版本由受信任代码决定。
YUQUE_CATEGORY_PIPELINES = {
    "tutorial": ("tutorial", 1),
}
# 阶段 5、6 接入对应流水线后，再添加 knowledge、tool_card。
```

### 3.2 类别判定

```python
@dataclass(frozen=True)
class Classification:
    category: str | None       # 跳过或未登记时为 None
    decided_by: str            # manifest / path_rule / none
    skip: str | None = None    # duplicate / deprecated / index / meta 等

class Manifest:
    def classify(self, ref: SourceRef) -> Classification:
        """先查单篇条目，再按最长路径前缀匹配目录规则；都没有时返回 decided_by="none"。"""
```

| 顺序 | 依据 | 结论 |
| --- | --- | --- |
| 1 | 清单 `[docs."知识库/slug"]` 条目 | 类别，或跳过及原因 |
| 2 | 清单 `[[path_rules]]`：知识库 + 目录路径前缀 | 类别；第一批只有“IT侠常用工具大全 → tool_card” |

导入服务按判定结果给出状态：

| 判定结果 | 状态 |
| --- | --- |
| 有类别，且在映射表中 | 导入 |
| 有类别，但不在映射表中（如 `troubleshooting`） | 跳过，报告“未接入” |
| 清单写明 `skip` | 跳过，报告原因 |
| 未登记 | 不导入，报告“未登记”，由维护者补写清单 |

两条依据都来自同一份清单，所以写成一个方法，不做可插拔的规则链。标题关键词判定在原型中已经过拟合，不进入导入流程；新文档的初判由维护者在补写清单时完成。可行性评估见[需求分析第 6 节](requirements-analysis.md#6-类别识别可行性)。

### 3.3 导入清单

清单是类别判定的唯一权威来源，随仓库版本管理，只含文档的路径、类别、跳过原因和可见性，不含正文：

```toml
# sources/yuque/manifests/itxia.toml
version = 2
source_type = "yuque"

[connector]                    # 平台参数，由语雀命令解释
group = "itxia"

[collections.help]             # 集合即语雀知识库
visibility = "public"

[collections.textbook]
visibility = "internal"        # 已确认：培训手册面向社员

[[path_rules]]                 # 目录规则：命中的文档无需逐篇登记
collection = "help"
path_prefix = ["IT侠常用工具大全"]
category = "tool_card"

[docs."help/install_win10"]
category = "tutorial"

[docs."textbook/recommended_tools"]
category = "tool_card"         # 目录外的工具合集
metadata = { tool_collection = true }   # 合集：每个工具一个父段，见 6.2

[docs."article/install_win10_from_scratch"]
skip = "duplicate"
canonical = "help/install_win10"

[docs."help/nju_wlan_qa_pro_plus_max_ultra"]
category = "troubleshooting"   # 已分类但第一批未接入
```

- 文档键用“知识库/slug”，便于人工阅读；来源身份用数字 ID（见 7.2）。slug 改名后清单条目找不到，报告提示更新。
- 载入时严格校验，出错直接失败：
  - 未知字段，或 `category` 和 `skip` 同时出现或都缺失；`skip` 必须是非空原因。
  - 类别不在语雀已定义集合内（[CATEGORIES](../../../sources/yuque/connector.py)）：第一批的 `tutorial`、`tool_card`、`knowledge`，以及已分类但暂未接入的 `troubleshooting`、`case`。
  - `canonical` 只能用于跳过条目，且必须指向清单中存在的单篇条目。
  - 可见性不是 `public` 或 `internal`。
  - `version` 不是整数 2，`source_type` 不是 `yuque`，`[connector]` 不是只含合法 `group`，知识库／文档标识非法，文档引用了未登记的知识库。
  - `path_rules` 必须为表数组，且只能包含 `collection`、`path_prefix`、`category`；知识库必须已登记，前缀必须为 1～10 项非空文本、每项最多 100 字；同一知识库的相同前缀不得重复。
  - 单篇 `metadata` 补丁只能用于有 `category` 的条目，必须是表，且不能包含平台命名空间 `yuque`。
- 单篇 `visibility` 可以覆盖知识库默认值。

仓库清单覆盖附录全部 74 篇（46 个单篇分类条目与 28 篇工具目录规则），另含 3 个重复跳过条目：`article/partition-resize` → `help/partition-resize`、`article/install_win10_from_scratch` → `help/install_win10`、`article/gagpcm` → `help/nju_network_guide`。

### 3.4 为什么不在服务端自动识别

1. 可靠信号（目录路径、知识库）是平台元数据。放进原文 API 会让 `ingestion` 依赖语雀，违背平台与内容分离。
2. 清单需要版本管理和评审，放在导入工具侧更自然；API 保持“同一请求总走同一流程”的可重复性。
3. 直接调用原文 API 的用户在 `preprocess.schema` 中人工指定类别即可，这与清单方式等价。

## 4. 语雀 Markdown 方言解析

### 4.1 结构：包装通用解析器

```python
class YuqueMarkdownParser:
    """先把语雀方言改写成标准 Markdown，再交给通用解析器；不改变通用解析器默认行为。"""
    def __init__(self, inner: MarkdownParser | None = None): ...
    def parse(self, raw: RawDocument) -> list[ContentBlock]:
        text = normalize_yuque(_decode(raw))          # 逐行改写，行数保持不变
        return self.inner.parse(replace(raw, content=text.encode()))
```

- 默认 `inner = MarkdownParser(pseudo_heading="nested_label")`。
- 在组合根注册：`parsers.register("text/x-yuque-markdown", YuqueMarkdownParser())`。
- 所有 schema 都能处理语雀 Markdown，例如以后语雀里的购机指南。

### 4.2 规范化规则

`normalize_yuque` 按下表顺序逐行改写，围栏代码块内的行不处理。每条规则只把一行改写为一行或空行，因此解析器给出的行号仍对应语雀原文行号。规则写成模块内的函数列表，调整时直接增删。

| 规则 | 输入 | 输出 |
| --- | --- | --- |
| 样式标签 | `<font>`、`<span>`、`<u>`、`<sup>`、`<sub>`、`<mark>`、`<strong>`、`<em>`（白名单） | 保留文字。白名单外的尖括号原样保留，例如 `<你的Windows用户名>` |
| 表格内换行 | 表格行中的 `<br>`、`<br/>` | `；` |
| 提示块 | `:::warning` … `:::` | 起始行改为 `> [!WARNING]`，块内行加 `> ` 前缀，结束行改为空行。tips／info／success／colorN 对应 NOTE，danger 对应 CAUTION |
| 折叠块 | 单行 `<details><summary>S</summary>…</details>` | `**S**：正文文本`；用 HTML 解析取文本，丢弃其中图片 |
| HTML 图片 | 独占一行的 `<img src alt>` | `![alt](src)`，交给通用图片规则 |
| 文内锚点链接 | `[文字](#xxxx)` | `文字`；其他链接（含语雀站内链接、官网地址）保留 |
| 删除线 | `~~…~~` | 删除；语雀把删除线内的行内代码写成 ``~~a~~`~~b~~`~~c~~``，只含删除内容的行内代码一并删除 |
| 空结构 | 空标题 `#### `、空加粗 `****`（含行内）、只含空样式的行、空引用行 `>` | 删除行内 `****`；空结构行改为空行，围栏代码内不处理。放在最后，前面规则删空的行也会被清掉 |

### 4.3 MarkdownParser 通用增强

以下能力属于标准 Markdown，放在通用解析器中，对所有 Markdown 输入生效：

| 能力 | 输出块 | 说明 |
| --- | --- | --- |
| 图片 | 独占一行的图片生成 `image` 块，文本为 `[图片：说明]` 或 `[图片：未提供文字说明]`，src 放 metadata；行内图片替换为同样的占位 | 与 HtmlParser 的占位格式一致，ParseStep 的缺失说明警告可直接生效 |
| 引用与提示块 | 连续 `>` 行生成 `quote` 块并去掉前缀。首行为 GitHub 提示标记时生成 `callout` 块：NOTE／TIP →【提示】（`level=note`）；IMPORTANT →【注意】（`level=note`）；WARNING →【警告】（`level=warning`）；CAUTION →【警告】（`level=caution`）。引用／提示块内的围栏代码不做图片替换等改写 | GitHub 提示块语法 |
| 空标题 | `#` 后没有文字的行忽略 | |
| 标题链接 | 标题（含伪标题）中的 `[文字](url)` 只保留文字 | 章节标题会进入父段标题和检索前缀；正文链接不变 |
| 伪标题 | 构造参数 `pseudo_heading`，见下 | 默认 `level2`，保持现有行为 |

`pseudo_heading` 有两种取值：

- **`level2`**（默认）：整行加粗视为二级标题，即现状。评测、购机指南的既有用例依赖这一行为。
- **`nested_label`**（语雀使用）：
  - 只有不超过 30 字、不含句内标点（，。；！？,;!?）的整行加粗才视为标题。
  - 标题级别为最近一个真实标题级别加一；还没有真实标题时为 2，最多 6。这样伪标题只会成为当前章节的子标题，不会切断上层结构。
  - 其余整行加粗按段落处理。

图片和引用块的文本形式变化会影响已有 Markdown 输入。实现时需运行解析与原文集成回归，并在[文档预处理](../preprocessing.md)记录变化。

## 5. 章节结构策略

### 5.1 组成

```python
@dataclass(frozen=True)
class SectionProfile:
    """三类文档的差异全部集中在这里。"""
    content_type: str
    max_parent_chars: int          # 子树超过该长度时按下一级标题下钻
    min_parent_chars: int          # 过短的父段并入相邻父段；0 表示不合并
    chunk_target_chars: int        # 子块目标长度
    chunk_min_chars: int           # 过短子块并入相邻子块；0 表示不合并
    table_rows_as_children: bool = False

@dataclass
class SectionNode:                 # 章节树节点，可任意深度
    heading: ContentBlock | None
    level: int
    blocks: list[ContentBlock]     # 本节导语：第一个子标题之前的内容
    children: list["SectionNode"]
    def size(self) -> int: ...     # 整棵子树的正文长度

class SectionedDocumentStrategy:   # 实现 StructureStrategy
    def __init__(self, profile: SectionProfile): ...
    def build(self, blocks, raw) -> list[SemanticContext]:
        # 过滤无说明图片 → build_tree → plan_parents → 每个父段 merge_blocks 生成子块 → SemanticContext
        ...
```

`build_tree`、`plan_parents`、`merge_blocks` 是 `sections.py` 的模块函数，不做构造注入：三类文档只差参数，没有第二种实现。

### 5.2 父段规划

1. **建树**：按标题级别建立章节树，不依赖固定级别。虚拟根收纳第一个标题前的内容；级别跳跃（H2 下直接 H4）按相对深度挂载。文档标题来自元数据，正文第一个 H1 不再被当作文档标题。
2. **包裹标题下降**：根只有一个子节点、根导语短于 `min_parent_chars`、且该子节点还有子节点时，把它的导语并入根导语，以其子节点作为顶层，重复判断。覆盖“文章标题重复为唯一 H1”的 3 篇文档。
3. **递归规划**：
   - 顶层节点的子树正文不超过 `max_parent_chars`，或没有子节点时，整棵子树为一个父段。
   - 否则节点导语（非空时）单独成父段，再对子节点递归。
   - 没有子标题的超长章节保持一个父段，由子块合并和 BudgetChunker 控制模型输入。
4. **文档导语**：第一个标题前的内容成为父段，标题为文档标题。无标题文档整篇一个父段。
5. **合并过短父段**：短于 `min_parent_chars` 的父段并入同一上级下前一个相邻父段；没有前一个时并入后一个；只有自己时保留。只在同级之间合并，以保证章节路径语义和块范围连续；合并后沿用接收方的标题和 key。

原型在快照上的估算（按去空白字符数）：

| 类别 | 父段数 | 父段长度 p50／p90／最大 | 估算子块数 |
| --- | --- | --- | --- |
| 教程 | 159 | 586／1949／5220 | 约 350 |
| 知识 | 79 | 529／1465／2311 | 约 180 |
| 工具 | 56 | 182／846／1426 | 约 80 |

教程的最大父段是一个没有子标题的 5220 字章节，按上述第 3 步保留为一个父段。

### 5.3 子块生成

`merge_blocks` 参照评测检索块的合并算法另写，复用 [strategies.py](../../../ingestion/strategies.py) 中的 `_keeps_with`、`_join`。[ReviewStrategy](../../../ingestion/strategies.py) 第一批不改：它的合并带有评测专用的栏目层级判断，为复用而重构只会扩大回归范围；两边都稳定后再考虑统一。

- **断点**：父段内的任一标题（含伪标题）开启新子块，标题与其后内容相连。连续标题尚无正文时按原文顺序带入后续块，key 与 `section` 取最后一个标题，定位覆盖这些标题。
- **相连规则**：
  - 沿用 `_keeps_with`：以“：”或“；”结尾的引导句与后文相连；连续列表项、表格行相连；“1、”“2、”式编号段落相连。
  - 新增：`callout` 块与前一块相连，使警告留在所属步骤内。
- **合并与拆分**：
  - 按原文顺序合并到 `chunk_target_chars`，短于 `chunk_min_chars` 的块并入前一块。
  - 超出模型预算的块交给 BudgetChunker，按段落或句子拆分。
- **代码块**：合并阶段不切开，但不标 `atomic`。超预算时由 BudgetChunker 按行切分，并在试运行报告中列出，避免一个长代码块导致整篇导入失败。
- **表格**：
  - `table_rows_as_children=True` 时，长于目标长度的表格按行组拆成多个子块。
  - 每个行组是父段中连续的数据行，表头写入 `retrieval_prefix`。
  - 行组目标长度远小于模型预算，正常不会再被 BudgetChunker 二次切分。
  - 其他配置下表格整体参与合并，超预算时由 BudgetChunker 按行切分并附表头（现有能力）。
- **图片**：
  - 无说明图片在建树前移除占位（含 Markdown 行内图片及 HTML 图文混排），仅整理含占位行的多余空白；其他行原样保留，包括代码与列表缩进、连续空格和行尾空白，块内换行保留。移除后仅剩空白的块整体过滤；占位不进入父段和子块，原文块序号与定位保持不变。
  - 每个父段原文区间中移除的占位数写入父段 metadata `omitted_images`。
  - 有说明的图片按段落保留。

### 5.4 标题、key、定位与检索文本

| 项 | 规则 |
| --- | --- |
| 父段标题 | 文档内章节路径，如“安装篇 > 三、开始安装”；文档导语和无标题文档用文档标题。超过 200 字时保留首尾两段，中间用“…”代替 |
| 父段 key | `context-` + 章节路径哈希；同名路径加出现次数，与现有 `_key` 规则一致 |
| 子块 key | `evidence-` + 所在小节标题哈希 + 小节内序号。修改一个小节只影响该小节的子块 key |
| 父段 locator | `block_start/end`，以及由内容块得到的 `line_start/end`，对应所取语雀 Markdown 的行号 |
| 子块检索文本 | `父段标题 + 换行 + retrieval_prefix + 换行 + 正文`，沿用现有 `evidence_input`。`retrieval_prefix` 由检索前缀步骤写入“目录路径 > 文档标题”，表格行组再追加表头 |

## 6. 三类流水线

### 6.1 步骤编排

增强步骤都是 `units → units` 的 PreprocessStep，插在 StructureStep 与 ChunkStep 之间。现有流水线只校验阶段衔接，这类步骤可以直接插入：

```text
tutorial@1  : Parse → Structure(Sectioned[TUTORIAL])  → CalloutWarning → TimeExpression → RetrievalPrefix → Chunk → Build → Validate
knowledge@1 : Parse → Structure(Sectioned[KNOWLEDGE]) → CalloutWarning → TimeExpression → RetrievalPrefix → Chunk → Build → Validate
tool_card@1 : Parse → Structure(ToolCard[TOOL_CARD])  → ToolIdentity   → CalloutWarning → SourceDateNotice → RetrievalPrefix → Chunk → Build → Validate
```

```python
# config/components.py（示意）：现有 pipeline() 增加 enrich 与 image_warning 参数
def pipeline(schema, strategy, enrich=(), *, image_warning=None):
    chunker = BudgetChunker(...)
    parse = ParseStep(parsers) if image_warning is None else ParseStep(parsers, image_warning=image_warning)
    return PreprocessPipeline([
        parse, StructureStep(strategy), *enrich, ChunkStep(chunker),
        BuildDocumentStep(document_schema=schema), ValidateStep(input_validator=chunker.validate),
    ])

registry.register("tutorial", 1, pipeline("tutorial", SectionedDocumentStrategy(TUTORIAL),
                  [CalloutWarningStep(), TimeExpressionStep(), RetrievalPrefixStep()],
                  image_warning="原文含未转写的截图，操作界面以原文链接为准"))
```

三个 schema 与输入格式无关，也可以处理微信或其他平台的 HTML、Markdown 教程。

### 6.2 配置参数

| 参数 | tutorial | knowledge | tool_card | 依据 |
| --- | --- | --- | --- | --- |
| max_parent_chars | 3000 | 2500 | 不适用 | 顶层章节 p90 约 2900～3000 字；工具条目按工具成父段，不按长度，见下文 |
| min_parent_chars | 150 | 150 | 0 | 并入“6.0、确定没问题了？”“引用”等短章节；工具条目不合并 |
| chunk_target_chars | 500 | 400 | 400 | 叶子小节中位数为 213／159／163 字，段落中位数约 50 字 |
| chunk_min_chars | 120 | 120 | 0 | 与评测检索块一致；工具小节不并入相邻工具 |
| table_rows_as_children | 否 | 是 | 否 | 知识类有 11 张比较表和速查表 |

工具条目不按长度规划父段，而是一个工具一个父段，由 ToolCardStrategy 实现：

- **单工具文档**：整篇一个父段，标题为文档标题；正文中的“简介／使用方法”等子标题只作为子块断点。最长约 3500 字（Markdown Here 插件），由子块合并控制模型输入。
- **合集文档**：清单在该文档的 `metadata` 中标记 `tool_collection = true`，第一批只有培训手册“常用软件”。按章节树拆到叶子章节，每个叶子章节（不再含子标题）即一个工具，成一个父段，标题为“分类 > 工具名”；文档导语和分类导语有正文时单独成父段，不带工具身份。这等价于复用 `plan_parents` 并取父段上限 0。
- **为什么由清单标记**：单工具文档也常有“简介／使用方法”子标题，微 PE、Markdown Here 等还有两级标题，按结构自动判断会把单工具误拆；合集只有一篇，人工标记最可靠。

按分类成父段会让一个父段含多个工具，无法写入单一工具名；按快照估算，“常用软件”4 个分类中有 3 个超过 1500 字，按长度规划也会使同一合集里有的分类成段、有的工具成段，因此统一按工具成父段。

参数是基于快照的初值，在真实样本试运行和检索抽查后校准。若参数变化影响已导入数据，按新 schema 版本注册（见第 9 节）。

### 6.3 增强步骤

| 步骤 | 输入 | 输出 |
| --- | --- | --- |
| CalloutWarningStep | `context.blocks` 中 `level=warning/caution` 的 callout 块，以及父段 locator 的 `block_start/end` | 落在父段内的写入该父段 warnings；落在第一个标题前的写入文档 warnings。单条截断到 300 字，并去重 |
| TimeExpressionStep | 父段正文；匹配“目前（2022年初）”“截至 2023 年”“（2025.11 更新）”等带明确年份的表述 | 父段 warning：“含时间限定表述‘…’，请结合来源日期判断是否仍适用”。每个父段只报第一处 |
| ToolIdentityStep | 文档标题、父段章节路径、`collection_path` | 单工具文档从“用途：工具名”解析 `tool_name`、`tool_purpose`，`tool_category` 取目录末段；合集文档的工具父段取路径末段为 `tool_name`、前一段为 `tool_category`，导语父段不写工具身份。写入父段 metadata，随检索结果返回 |
| SourceDateNoticeStep | 文档 `source_date` | 文档 warning：“本条目内容最后更新于 YYYY-MM-DD，软件版本、下载地址和界面可能已变化，请以官网为准”。只写入日期本身，不计算“距今多久”，避免提示随时间失真；没有日期时提示“更新日期未知”。第一批只用于工具条目 |
| RetrievalPrefixStep | `collection_path`、文档标题 | 每个子块的 `retrieval_prefix` 前置“目录路径 > 文档标题”，略去与父段标题重复的部分；与已有表头前缀以换行组合。BudgetChunker 拆分子块时保留该前缀 |

风险提示做成步骤而不放进章节策略，是因为全局提示要写入文档 warnings，而结构策略只返回父段，只有步骤能访问 `PreprocessContext.warnings`。它依赖的 `block_start/end` 由 SectionedDocumentStrategy 保证写入。

ParseStep 的图片警告文案改为构造参数。三类流水线使用“原文含未转写的截图，操作界面以原文链接为准”，其他流水线保持现有文案。

### 6.4 产出示例

| 文档 | 类别 | 预期父段（节选） |
| --- | --- | --- |
| 面向小白的 Windows10/11 安装/重装教程 | 教程 | 文档导语；准备篇；安装篇 > 二、进入装机盘；安装篇 > 三、开始安装；激活设置篇 > 三、激活吧！我的Windows！…… |
| Windows 10/11 的版本与激活详解 | 知识 | 包裹 H1 下降后：0、什么是Business/Consumer Editions？；1、自行安装Windows 10时版本的选择；2、数字权利激活问题…… |
| Windows系统功能快速查阅表 | 知识 | 一个父段（无标题，标题为文档标题），表格按行组成为子块，每个子块检索文本带“功能 \| 命令／快捷键”表头 |
| 文件占用查看：WizTree | 工具 | 一个父段；`tool_name=WizTree`、`tool_purpose=文件占用查看`、`tool_category=文件占用和系统清理`；子块前缀“IT侠常用工具大全 > 文件占用和系统清理” |
| 常用软件（培训手册） | 工具 | 每个工具一个父段：驱动相关 > Display Driver Uninstaller（DDU）；驱动相关 > Snappy Driver Installer（SDI）；硬件检查和测试 > Aida64……；文档开头的两段说明成为导语父段。`tool_name`、`tool_category` 分别取工具名与分类 |

## 7. 导入工具

### 7.1 平台读取

```python
@dataclass(frozen=True)
class YuqueDocRef:
    doc_id: int
    book: str
    slug: str
    title: str
    toc_path: tuple[str, ...]      # 祖先目录节点标题；目录节点本身也可以是文档
    content_updated_at: datetime

class YuqueClient(Protocol):
    def list_docs(self, book: str) -> list[YuqueDocRef]: ...
    def read_markdown(self, ref: YuqueDocRef) -> str: ...
```

| 实现 | 用途 | 说明 |
| --- | --- | --- |
| YuqueOpenApiClient | 正式导入 | 读取 `GET /api/v2/repos/{group}/{book}/toc`、`/docs`、`/docs/{slug}`（取 `data.body`，不使用草稿）。请求头为 `X-Auth-Token`，Token 来自环境变量 `YUQUE_TOKEN`。用标准库 urllib，与现有 Embedding 适配器一致。前一次请求结束后至少间隔 0.5 秒再请求，测试可设为 0；默认 timeout 为 30 秒。docs 列表按 offset／limit 分页，每页上限 100，读取至不足一页 |
| YuqueSnapshotClient | 离线试运行与测试 | 读取本地快照目录：`<dir>/<book>/toc.json`、`docs.json`、`<slug>.md`。OpenAPI 模式可用 `--save-snapshot` 生成快照 |

两种实现是必要的：快照让试运行和单测不依赖网络与 Token。

[YuqueConnector](../../../sources/yuque/connector.py) 把客户端适配为通用 SourceConnector：`list()` 遍历构造时传入的知识库，把 YuqueDocRef 映射为 SourceRef（`collection=book`、`key="book/slug"`、`canonical_locator="doc:<id>"`、清洗后的标题、`collection_path=toc_path`，doc_id、slug、原标题放 `extra`）；`fetch(ref)` 读取 Markdown，返回原文、原文链接与平台元数据。

两种客户端复用同一目录路径计算。`<dir>/<book>/toc.json` 与 `docs.json` 均采用 OpenAPI 响应结构 `{"data": [...]}`，docs 保存合并后的完整分页列表，不保存响应头或认证信息。目录项包含 `type`（DOC／TITLE／LINK）、`title`、`uuid`、`parent_uuid`、`url`（文档 slug）、`doc_id`；文档项包含 `id`、`slug`、`title`、`content_updated_at`（带时区的 ISO 8601，如 `2025-11-23T13:23:51.000Z`）。正文为 `<slug>.md` UTF-8 文本。`toc_path` 沿 `parent_uuid` 向上取祖先标题，再按根到叶排序，不包含自身；祖先可以是 TITLE 或 DOC，不在目录中的文档路径为空。缺失或非法的列表／目录文件会启动失败；单篇正文文件读取失败记入该篇报告后继续。

`YUQUE_TOKEN` 默认空，OpenAPI 模式启动时校验；`YUQUE_API_BASE` 默认 `https://www.yuque.com/api/v2`，留空也使用默认地址。真实接口格式与账号权限待 Token 到位后补测。

### 7.2 来源身份与元数据

身份、链接、标题和平台元数据由 `YuqueConnector.fetch` 生成，通用的 `build_request(source_type, fetched, manifest, schema=..., version=..., classification=...)` 再合并清单的单篇 `metadata` 补丁与可见性，并在平台命名空间中写入 `classified_by`。标题清洗规则为：去掉【推送归档】等方括号前缀、“教程 \|”“Tips \|”等栏目前缀和末尾的 ⭐，原标题存为 `title_raw`。

schema/version 由组合根映射传入。栏目前缀简化为开头不超过 20 字的“栏目 \|”（兼容全角竖线与空栏目），不会删除标题中间的方括号或星号。请求 dict 经原文 API 同一个 `RawSourceImportSerializer` 与 `import_raw_dtos` 转换为 DTO，复用标题长度、日期与目录路径等字段校验。清洗后为空或超出契约范围会记为单篇 `INVALID_REQUEST`；元数据时间用带时区的 ISO 8601 保留完整更新时间。

```json
{
  "source": {
    "source_type": "yuque",
    "canonical_locator": "doc:55035323",
    "visibility": "public",
    "source_url": "https://www.yuque.com/itxia/help/install_win10"
  },
  "preprocess": {"schema": "tutorial", "version": 1},
  "raw": {
    "content": "<语雀 Markdown 原文>",
    "media_type": "text/x-yuque-markdown",
    "metadata": {
      "title": "面向小白的 Windows10/11 安装/重装教程",
      "source_date": "2025-11-23",
      "collection_path": ["Windows 问题相关", "Windows 10/11 安装/激活问题"],
      "yuque": {
        "doc_id": 55035323, "book": "help", "slug": "install_win10",
        "title_raw": "面向小白的 Windows10/11 安装/重装教程",
        "content_updated_at": "2025-11-23T13:23:51Z", "classified_by": "manifest"
      }
    }
  }
}
```

| 字段 | 规则 |
| --- | --- |
| `canonical_locator` | `doc:<语雀文档数字 ID>`。slug 可能改名或是随机串，数字 ID 稳定；复制到其他知识库的副本 ID 不同，由清单去重 |
| `source_url` | 当前 slug 的网页地址，用于引用和查看截图 |
| `visibility` | 单篇覆盖值，否则取知识库默认值 |
| `source_date` | 语雀内容最后更新时间，按北京时间取日期。它是更新日期而非首发日期，元数据中保留原始时间 |
| `collection_path` | 新增的通用控制字段：来源内的目录路径，字符串数组，最多 10 项，每项不超过 100 字。不限于语雀，其他平台的栏目或合集同样适用 |
| `yuque` | 来源专有字段，按现有规则原样进入文档 metadata，不参与预处理 |

### 7.3 导入服务

导入服务与平台无关，见 [sources/importing.py](../../../sources/importing.py)：

```python
class SourceImportService:
    def __init__(self, connector: SourceConnector, manifest: Manifest,
                 category_pipelines: Mapping[str, tuple[str, int]], submit): ...
    def run(self, refs: Iterable[SourceRef], *, only=None, read_errors=None) -> ImportReport: ...
```

每篇文档的处理顺序：

1. `manifest.classify(ref)` 判定类别，按 3.2 的状态表决定是否导入；不导入的直接记录。
2. 查映射表得到 schema@version。
3. `connector.fetch(ref)` 读取 Markdown，`build_request` 组装原文导入请求。
4. 调用注入的 `submit(source, raw, schema, version)`：正式导入依次调用 `preprocess_raw` 与 `import_processed`，试运行提供账号时为 `preprocess_raw`，不提供账号时直接调用 `registry.process`。试运行只预处理不编码不保存。
5. 记录父段数、子块数、`reused`、警告和错误码。

`submit` 以函数注入，单测可以替换为假实现，不需要数据库或模型。

`submit` 返回 `SubmissionResult(document, result)`，其中 `result` 是现有 `ImportResult`，试运行时为空。正式命令保留 `preprocess_raw` 生成的文档供报告统计，再调用 `import_processed` 编码与保存，只预处理一次、不改变公共导入返回结构。试运行成功状态为 `preprocessed`，汇总中单独计数。报告收集文档、父段与子块 warnings 并去重，每条最多显示前 30 个字符，超长时加“…”；每篇一行，不打印正文。失败行保留完整 DomainError 错误码与消息，边界校验记录 `INVALID_REQUEST`。

`run(refs, only=...)` 支持可选的单篇过滤。未指定 `--only` 时检查所有清单单篇条目是否在列表中；指定后只检查请求的文档，避免对主动排除的知识库／文档产生缺失警告。

报告示例：

```text
doc                                 category(by)                status        parents children detail
help/install_win10                  tutorial(manifest)          imported      12      26
help/giq7z502ohos1d3u               tool_card(path_rule)        reused        1       1
help/nju_wlan_qa_pro_plus_max_ultra troubleshooting(manifest)   skipped       -       -        未接入
article/install_win10_from_scratch  -(manifest)                 skipped       -       -        duplicate → help/install_win10
help/new_doc                        -                           unregistered  -       -        请在清单中登记类别或 skip
summary: imported=… reused=… skipped=… unregistered=… failed=…
```

### 7.4 命令行

```sh
# 离线试运行：读取本地快照，不需要 Token、Embedding 和数据库写入
.venv/bin/python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
  --snapshot .runtime/yuque-snapshot --dry-run

# OpenAPI 试运行并保存快照：先配置并加载 YUQUE_TOKEN
.venv/bin/python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
  --save-snapshot .runtime/yuque-openapi-snapshot --dry-run

# OpenAPI 正式导入单篇：账号需 maintain_source（internal 文档另需 read_internal）
.venv/bin/python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
  --username maintainer --only help/install_win10
```

| 参数 | 说明 |
| --- | --- |
| `--manifest` | 必填，导入清单；读取清单中出现的知识库 |
| `--snapshot DIR` | 从本地快照读取，不需要语雀 Token；缺省使用 OpenAPI |
| `--save-snapshot DIR` | 仅 OpenAPI 模式，与 `--snapshot` 互斥；先保存后导入，可与 `--dry-run` 同时使用。保存目录应放在被忽略的 `.runtime/` 下 |
| `--only` | 只导入指定文档（知识库/slug），可重复；通常只读取涉及的知识库。保存快照时始终读取清单全部知识库及已分类正文 |
| `--dry-run` | 只预处理并输出报告，成功状态 `preprocessed`；不提供账号时无需数据库连接，提供账号时校验权限 |
| `--username` | 非试运行时必填，以该账号的权限执行导入，与 API 权限校验一致 |

保存快照采用先下载、再用 `YuqueSnapshotClient` 导入的方式。保存范围是清单内所有知识库的目录、完整文档列表与所有已分类正文（含目录规则命中和未接入类别），覆盖第一批 74 篇；跳过、未登记不保存正文。`--only` 只限制导入，不缩小保存范围。任何正文读取失败均进入报告，包括未接入类别和未被 `--only` 选中的文档，保存失败的旧正文会移除，其他文档继续；成功读取的未接入类别仍不会导入。保存期间发生 401／403 会在导入前终止，已下载的文件可能保留。文件写入失败终止整批；失败快照可能不完整，应重跑补齐。

### 7.5 错误处理

| 情况 | 处理 |
| --- | --- |
| 清单格式错误、未知类别或字段 | 启动时失败，不处理任何文档 |
| 未登记、类别未接入、清单跳过 | 记入报告，不导入 |
| 清单条目在语雀中找不到 | 报告警告，提示标识可能已改名 |
| 单篇预处理或导入失败（DomainError） | 记录错误码，继续下一篇；整批结束后命令以非零状态退出 |
| 非试运行但 Embedding 未配置 | 启动时失败 |
| OpenAPI 模式缺少 Token | `YUQUE_NOT_CONFIGURED`，启动即失败，提示配置环境变量 `YUQUE_TOKEN` |
| 语雀 401／403 | `YuqueAuthenticationError`（通用 `SourceAccessError` 的子类），不会被导入服务当作单篇失败；命令转为 CommandError 终止整批，提示检查 `YUQUE_TOKEN` 与知识库权限。不会回滚之前已导入的文档 |
| 单篇详情 429 | `YUQUE_RATE_LIMITED`，当前篇记为失败并继续；修正后用 `--only` 重跑或整批重跑。不实现重试队列 |
| 单篇详情其他 HTTP、网络错误或超时 | `YUQUE_UNAVAILABLE`，当前篇失败并继续；不输出服务错误正文或底层异常详情 |
| 单篇详情 JSON、响应结构或 body 类型异常 | `INVALID_YUQUE_RESPONSE`，当前篇失败并继续 |
| 目录或文档列表读取失败 | 没有可归属的单篇，整批终止并输出相应错误码；命令先列完本次涉及的知识库，再处理正文，因此列表失败时不导入任何文档 |
| 保存快照写入失败 | `SNAPSHOT_WRITE_FAILED`，终止整批，提示检查目录与文件权限 |

Token 只从环境变量读取，不写入日志、报告或快照文件。

### 7.6 更新与同步

- 重新运行命令即可同步：未变化的文档返回 `reused=true`。按现有设计，重复导入仍可能调用 Embedding，第一批规模下可以接受，因此不提供按日期增量的选项。
- 目录移动会改变 `collection_path`，进而改变检索前缀和内容哈希，重新导入时更新。
- 语雀中删除的文档或清单改为跳过的文档，已导入的来源不会自动删除，当前 API 也没有删除入口。如需清理，作为后续能力另行设计。

## 8. 契约变化汇总

| 契约 | 变化 | 兼容性 |
| --- | --- | --- |
| 原文 API 媒体类型 | 新增 `text/x-yuque-markdown` | 新增，不影响已有类型 |
| 预处理 schema | 新增 `tutorial@1`、`tool_card@1`、`knowledge@1` | 新增 |
| `raw.metadata` | 新增通用控制字段 `collection_path` | 可选字段 |
| MarkdownParser | 识别图片、引用、提示块和空标题；新增 `pseudo_heading` 参数 | 默认伪标题行为不变；图片与引用的文本形式变化，需回归 |
| ParseStep | 图片警告文案可配置 | 默认文案不变 |
| 现有三种 schema 的策略 | 无 | — |
| 存储、检索、标准导入 API | 无 | — |
| 命令与配置 | `import_yuque` 支持 OpenAPI、`--snapshot` 与 `--save-snapshot`；`INSTALLED_APPS` 包含 `sources`（无模型、无迁移）。阶段 4 增加 `YUQUE_TOKEN`、`YUQUE_API_BASE` 与容器透传 | 快照模式无需 Token，原有参数语义保留 |

## 9. 扩展点

变化集中在四处：SectionProfile 参数、增强步骤列表、组合根的 schema 注册与类别映射、YuqueClient 实现。常见场景：

| 场景 | 需要做的 |
| --- | --- |
| 接入排障指南 | 新增 SectionProfile，以及导读全局提示、风险层级等增强步骤；注册 `troubleshooting@1` 并加入映射表 |
| 接入单案例 | 用 `max_parent_chars` 取极大值的 SectionProfile 实现整篇一父段，或给 ExperienceCaseStrategy 加该模式；注册并加入映射表 |
| 调整某类参数 | 注册新版本（如 `tutorial@2`），映射改指向新版本；旧版本保留便于对比 |
| 其他平台的教程 | 直接使用 `tutorial@1`，配合 `text/html` 或 `text/markdown` |
| 新平台 | 实现 SourceConnector、编写清单与继承 SourceImportCommand 的薄命令；有自己的方言时新增方言解析器，见[来源连接器改造方案](../source-connector-design.md) |
| 增加自动分类信号 | 在 `Manifest.classify` 的目录规则之后增加判定；规则变多、需要独立替换时再拆成规则对象 |

## 10. 测试与验收

### 10.1 单元测试

不访问网络、数据库或模型。合成样本写在测试代码中：`fixtures/` 被忽略，也不能提交文章原文。

| 用例文件 | 重点 |
| --- | --- |
| `tests/unit/test_preprocessing_parsers.py`（扩充） | 图片块与占位、引用与提示块、空标题、`pseudo_heading` 两种取值；现有用例不变 |
| `tests/unit/test_yuque_markdown.py` | 每条方言规则、行号保持、占位符与代码块保真、折叠块、表格内换行 |
| `tests/unit/test_sections.py` | 自适应顶层、包裹标题下降、超长下钻与导语父段、过短父段合并、无标题文档、子块相连规则、key 稳定、标题截断、表格行组、图片计数 |
| `tests/unit/test_enrichment_steps.py` | 提示块进入父段或文档 warnings、时效表述、来源日期提示（含日期缺失）、工具身份、检索前缀与表头组合 |
| `tests/unit/test_source_manifest.py` | 通用清单：单篇条目优先于目录规则、目录规则命中、未登记、跳过、未接入类别、元数据补丁、清单校验 |
| `tests/unit/test_yuque_importer.py` | 快照连接器和假提交函数：试运行不编码、单篇失败不中断、整批访问错误终止、报告状态、标题清洗与元数据、可见性来自清单 |
| `tests/unit/test_yuque_client.py`、`tests/unit/test_yuque_openapi.py` | mock HTTP 边界，不开 socket；固定间隔与 timeout、网络与响应格式错误、认证独立异常、快照读写失败、错误消息不泄露 Token |

### 10.2 集成测试

`tests/integration/test_yuque_openapi.py`：本地临时 HTTP 服务模拟目录、分页文档列表与详情，验证请求路径与认证头、祖先路径、401／403 终止、429 与其他详情错误单篇失败后继续、列表失败、缺少 Token 启动失败、74 篇合成快照覆盖未接入类别并兼容离线模式、日志／报告／快照不含 Token。正式导入用例使用隔离 PostgreSQL 与模型替身；不访问真实语雀。沙箱不支持 socket 时至少执行 collect-only，集成与全量测试由隔离环境复核。

`tests/integration/test_yuque_ingestion.py`：使用隔离 PostgreSQL、项目账号的 API Token 认证和明确的模型替身，不访问语雀。当前覆盖教程原文 API 与合成快照管理命令：命令只导入教程、重复执行全部 reused、未登记／未接入／重复副本不写入、internal 来源权限与批次失败退出。后续阶段再扩充知识与工具 API 用例，检查：

- 检索返回带章节路径的父段标题、warnings、工具 metadata 和命中定位。
- 重复导入返回 `reused`。
- internal 文档对普通调用方不可见。

### 10.3 真实样本验收

人工执行，结果注明日期，不提交快照。以下是第一批全部完成时的验收内容，实际按类别分摊到阶段 4～6 执行：

1. **OpenAPI 实测**：用团队 Token 读取三个知识库的目录和 5 篇文档，对比 `body` 与网页导出的差异，必要时调整方言规则。
2. **74 篇试运行**：
   - 0 失败。
   - 父段、子块规模与 5.2 的估算同量级。
   - 跳过和未登记与清单一致。
   - 被 BudgetChunker 切分的代码块逐一检查。
3. **人工抽查 9 篇**：
   - 篇目：教程 `install_win10`、`hello_my_pc`、`change_win_account_name`；工具 `sdi-driver`、`giq7z502ohos1d3u`、`recommended_tools`；知识 `win10_activation`、`windows_short_commands`、`slang`。
   - 检查项：正文无样式标签和图片地址、占位符保留、章节路径正确、步骤未断开、warnings 完整。
4. **检索抽查**：在开发环境用真实模型导入后，检查期望文档是否出现在前 5 个父段，结果作为参数校准依据，不作为自动化通过标准：

   | 查询 | 期望命中 |
   | --- | --- |
   | Windows 怎么改用户名 | Windows 更改用户名教程 |
   | 新电脑开机怎么跳过联网 | 新笔记本验机／设置指南 5.1 |
   | 查看哪个文件夹占空间大 | WizTree／SpaceSniffer／TreeSize |
   | SDI 装驱动要注意什么 | Snappy Driver Installer（含 Alps 警告） |
   | 重置 Winsock 的命令 | Windows系统功能快速查阅表对应行组 |
   | 数字权利激活是什么 | Windows 10/11 的版本与激活详解 |
   | ProgramData 文件夹是干什么的 | C盘文件夹的功能与分布 |
   | 独显和核显有什么区别 | 黑话指南或笔记本核心硬件科普 |

## 11. 实施步骤

分 6 个阶段实现，每个阶段完成后系统都可运行，新增功能可经原文 API 或导入命令实际验收。先只用操作教程打通从语雀读取到检索的完整链路，确认可用后再扩充知识和工具条目。各阶段的实现内容、系统状态、验收方法和文档同步见[分阶段实现方案](implementation-phases.md)。

| 阶段 | 内容 | 需要 Token |
| --- | --- | --- |
| 1. 语雀 Markdown 解析 | MarkdownParser 通用增强、YuqueMarkdownParser、注册媒体类型 | 否 |
| 2. 教程流水线 | 章节策略、风险提示、时效提示、检索前缀、`collection_path`，注册 `tutorial@1` | 否 |
| 3. 导入命令（快照） | 快照客户端、清单、导入服务、`import_yuque`；映射表只有教程 | 否 |
| 4. 语雀读取与教程验收 | OpenAPI 客户端、保存快照、28 篇教程真实导入与检索抽查 | 是 |
| 5. 知识流水线 | 表格行组、知识参数，注册 `knowledge@1` 并加入映射 | 否 |
| 6. 工具条目流水线 | 工具身份、来源日期提示，注册 `tool_card@1` 并加入映射；74 篇整体验收 | 否 |

## 12. 风险与待确认

| 项 | 影响 | 应对 |
| --- | --- | --- |
| OpenAPI `body` 与网页导出方言不一致 | 规范化规则可能需要增删 | 阶段 4 先实测；规则是独立的行函数，可以单独调整 |
| 参数基于快照估算 | 父段过大或过碎 | 试运行与检索抽查后校准，必要时注册新版本 |
| 截图中的关键信息无法检索 | 例如校园网收费标准主要在截图中 | warnings 提示查看原文；建议维护者在语雀补文字说明；OCR 不在本批 |
| 子块 key 按小节加序号 | 同一小节正文增删可能移动该小节后续子块的 key | 与评测检索块的取舍一致，父段 key 不受影响 |
| 通用解析增强改变图片与引用的文本形式 | 已导入的 Markdown 资料重新导入时内容哈希变化 | 当前只有测试数据；实现时回归并在文档预处理中记录 |
| 子块合并逻辑与评测策略各有一份 | 两处规则可能逐渐分叉 | 共用相连判断函数；第一批稳定后评估是否统一 |
| 语雀 Token 尚未到位 | 阶段 4 代码已实现，真实接口与教程验收无法完成 | 本次离线单测通过，本地 HTTP 集成测试已新增且可收集，运行由隔离环境复核；接口实测、方言差异调整、真实目录 slug 核对、真实快照保存及教程验收待 Token 到位后补测；其余待确认项已于 2026-10-09 确认，见[需求分析第 7 节](requirements-analysis.md#7-范围外与待确认) |
