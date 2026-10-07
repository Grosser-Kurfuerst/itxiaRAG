# 首期技术设计：最小混合检索知识库

目标是：**接收已整理的文档，保存父子内容，执行关键词与向量混合召回，经可编排的召回后处理流水线后返回完整父上下文**。默认流水线使用 RRF；知识库不生成最终答案。

本文统一维护当前模块、数据契约、流程与阶段验收。业务范围见[总体需求](../requirements.md)，选择理由和研究出处见[技术选型](../technology-selection.md)，安装与调用见 [README](../../README.md)。

**实现状态：**独立路线门槛、原始分数保留和召回后处理流水线已实现。默认流程为 `MultiRouteRecall → PostRecallPipeline → ContextReader`；模型重排与持久化关键词索引只保留扩展方向，不作为运行依赖。

## 1. 系统边界

当前输入是标准化 JSON，不是公众号 URL、HTML 或 Markdown 原文件。维护者或外部程序负责获取获准资料、脱敏、整理正文和指定父子关系。系统不调用解析器，不自动划分父子段落，也不使用 LLM 识别文档类型或改写查询。

保留 Token 认证、`maintain_source` 维护权限、`read_internal` 内部资料权限；文档范围仅为 `visibility=public/internal`。公开指对已认证普通调用方可见，不开放匿名接口。Embedding 可连接本地或获准的外部服务。

不实现审核、自动放行、系统发布账号、构建切换、撤回、审计、任务队列、retry/resume、健康探针、维护模式、生成模型、反馈或知识图谱。失败直接返回错误，修正后重新提交。

## 2. 模块与依赖方向

```text
api → contracts（校验、DTO） → ingestion.pipeline
                                  ├─ EmbeddingProvider → HTTP 模型适配器
                                  └─ DocumentStore → PostgreSQL

api → retrieval.service → MultiRouteRecall
                           ├─ KeywordRetriever → PostgreSQL
                           └─ VectorRetriever → EmbeddingProvider + PostgreSQL
                        → PostRecallPipeline（有序步骤列表）
                           └─ 默认：RRF → 父段聚合 → top_k 父段
                        → ContextReader → 完整父段、来源与命中定位

未来：SourceConnector → RawDocument → DocumentPreprocessor
                                  → ProcessedDocument → 现有导入入口
```

| 模块 | 责任 | 不负责 |
| --- | --- | --- |
| [contracts/](../../contracts/) | DTO、Protocol、导入和查询 Serializer | ORM、模型调用和解析实现 |
| [ingestion/](../../ingestion/) | 校验 → 编码 → 保存；预处理插件注册表 | 获取推文、解析或划分段落 |
| [embeddings/](../../embeddings/) | HTTP 编码适配器、批次顺序与向量校验 | 数据库和召回排序 |
| [catalog/](../../catalog/) | 三张业务表、事务保存、可见范围、父段读取 | 模型供应商协议、审核发布 |
| [retrieval/](../../retrieval/) | 关键词／向量召回、召回后处理流水线、结果组装 | 导入与文章清洗 |
| [config/components.py](../../config/components.py) | 组合根，选择和注入具体适配器 | 业务规则 |
| [api/](../../api/) | 两个 HTTP 入口、认证、输入校验和响应 | 另写一套导入或检索逻辑 |

采用轻量的端口与适配器、策略模式和依赖注入，不给所有 ORM 操作套通用 Repository。召回路线和召回后处理分别通过协议注入；后处理步骤以有序列表编排，允许增加步骤或调整兼容步骤的顺序。只隔离确实会变化的文档保存、Embedding、召回、排序、上下文读取与预处理。

## 3. 标准化文档与预处理插件

### 3.1 数据契约

[contracts/types.py](../../contracts/types.py) 是内部协议依据，[contracts/serializers.py](../../contracts/serializers.py) 是导入校验依据。JSON 样本见 [basic.json](../../fixtures/iteration1/basic.json)。

| DTO | 字段与含义 |
| --- | --- |
| `SourceSpec` | `source_type` 来源渠道；`canonical_locator` 渠道内稳定键；`visibility` 可见范围；`source_url` 原文地址 |
| `RawDocument` | `content` 原始字节；`media_type` 格式；`metadata` 采集元数据，仅供未来插件使用 |
| `ProcessedDocument` | `title`、`document_schema`、`schema_version`、`source_date`、`metadata`、`warnings`、`contexts` |
| `ContextDraft` | `key` 文档内稳定父段键；`title`、`body` 完整上下文；`locator` 原文定位；`metadata` 适用对象等附加信息；`warnings`；`children` |
| `EvidenceDraft` | `key` 父段内稳定子块键；`body` 检索正文；`locator`、`metadata`、`warnings` |

数组顺序就是段落顺序，数据库保存为 `ordinal`。父子 key 在各自范围内唯一；正文非空，子块正文必须能在所属父段中找到。不自动补父段、生成摘要或拆段。Markdown 正文原样保存，包括行尾双空格。

每篇 1～100 个父段，每父段 1～100 个子块，整篇最多 1000 个子块；JSON 请求体上限 2 MiB。父段正文上限 100000 字符、子块 32000 字符，key 最多 100 字符。字符上限不等于模型 token 上限，调用方仍需按所用模型准备合适长度的子块。

`source_type` 表示平台，`document_schema` 表示预处理所需的文档结构，两者独立。例如同为 `yuque`，可以分别注册维修经验和基础知识的预处理器。结构专有字段放 `metadata`，不为每种文章增加表。可见范围只存在来源上，插件不能通过 metadata 改变权限。

### 3.2 插件接入方式

- 连接器遵循 `SourceConnector.fetch(locator) → RawDocument`，同一语雀连接器可服务不同内容类型。
- 预处理器遵循 `DocumentPreprocessor.process(raw) → ProcessedDocument`，自主选择规则、格式解析或未来的模型方法。
- `PreprocessorRegistry.register(schema, version, processor)` 显式注册策略，`process(raw, schema, version)` 调用并校验产物。空注册表拒绝处理，重复注册报错。
- 未来在 `config/components.py` 注册实现，由来源导入入口选择 Schema。插件输出仍须通过公共 Serializer 校验；不能让请求提供 Python 路径或任意加载代码。
- **本轮只有协议、注册机制和合约测试，没有具体预处理器，也没有原文导入 HTTP 入口。**当前 API 直接接收 `ProcessedDocument`。接入未来插件后，处理结果继续交给 `import_processed`，不改写存储与检索。

第一种笔记本评测插件未来按“一台笔记本一个父段，多台分开”生成 DTO；这不是所有文档的固定划分模式。

语雀、微信与维修记录的资料准备和后续读取方式见[来源接入说明](source-ingestion-plan.md)。

## 4. 存储设计

三张业务表，另有 Django 认证依赖表：

| 表 | 主要字段 | 用途 |
| --- | --- | --- |
| `knowledge_source` | UUID、source_type、canonical_locator、source_url、visibility、title、source_date、document_schema、schema_version、metadata、warnings、content_hash、embedding_space、时间戳 | 一份来源的当前文档与出处；`(source_type, canonical_locator)` 唯一 |
| `context_unit` | UUID、source 外键、key、ordinal、title、body、locator、metadata、warnings | 完整父上下文；`(source, key)` 唯一 |
| `evidence_unit` | UUID、context 外键、key、ordinal、body、retrieval_text、locator、metadata、warnings、embedding | 召回子块及其向量；`(context, key)` 唯一 |

一个子块对应一个 embedding，编码文本固定为 `父段标题 + 换行 + 子块正文`。父段不单独编码。文档级 metadata 用于保留来源信息，不投影为召回条件，也不默认完整发送给调用方；父段 metadata 随结果返回，子块 metadata 和 warnings 保存供维护或后续扩展，不默认返回。回答所需的风险警告应写入文档或父段 warnings，不能只放在子块中。子块 locator 应保持简短，只记录章节、段落号或字符偏移等定位信息，不放正文或大型附加数据。

保存采用 `DocumentStore.save(...)` 协议，默认 `DjangoDocumentStore`。现阶段向量保存在 PostgreSQL JSONB 数组；`VectorRetriever` 在数据库完成范围过滤后逐批读取向量，用余弦计算精确 top-N，不预截断候选。复杂度约 `O(N × D)`，适合小规模验证；无 ANN 索引，不承诺大规模性能。需要规模化时替换为 pgvector 字段和 Retriever，DTO、API、RRF 不变。

### 4.1 重复与更新

同一来源、规范化 DTO 内容及 embedding_space 相同，返回 `reused=true`，不增加记录。最小实现先完成编码再由存储判断复用，因此重复提交仍可能调用 Embedding；当前不增加缓存或额外预检查。

内容更新时按稳定 key 更新父子行，保留仍存在段落的 ID；删除本次输入中不存在的段落。返回 ID 指向当前内容，不承诺不可变历史引用。没有版本表、候选、发布指针或旧引用统一失效机制。

Embedding 在数据库事务外完成；全部向量有效后一次事务保存来源、父段、子块。任意写入失败回滚本次写入，已有文档保留。这个事务用于防止半份文档，与版本发布流程无关。正常导入返回 HTTP 200；没有持久任务状态。

统一入口为 [import_processed](../../ingestion/pipeline.py)，通过注入 `embedder` 与 `store` 组合编码和保存。权限与内容校验未通过时不调用模型；[HTTP 适配器](../../embeddings/openai_compatible.py) 验证返回索引、数量、维度、有限值与非零向量后才交给存储。

### 4.2 配置身份

模型地址、模型名、维度、显式 revision、查询指令和编码模板共同生成 `embedding_space`，查询仅使用同一空间的数据。更换模型或编码方式须重新导入，不把同维度当作同模型。

RRF 的 k、每路候选数、路线门槛和后处理步骤列表属于查询运行配置；最终 top_k 由请求指定。修改这些配置不重算向量。数值配置放 Django settings／环境变量，步骤列表由组合根显式构造，不建数据库配置单例或复杂 profile 管理。

## 5. 检索流程

### 5.1 当前已实现流程

1. 接收 `query` 原样作为检索文本，校验 `top_k` 与可选过滤条件；不做查询改写或意图识别。
2. 根据当前账号生成不可由请求扩大权限的 `SearchScope`。来源 ID 过滤只缩小召回范围；两路使用同一 Scope。
3. 关键词路先按 Scope 从 PostgreSQL 读取全部可见子块，再对 `retrieval_text` 和查询使用相同分析器：jieba 中文分词、英文大小写统一、保留型号／错误码、移除少量问句停用词。Python BM25 根据词频、文档频率和长度评分，按本路线门槛过滤后取 top-N；同分按子块 UUID 排序。
4. 向量路调用 `embed_query`，过滤同一向量空间，计算余弦并应用可选门槛。`MultiRouteRecall` 依次收集两路结果，每路最多 100 个子块，保留原始分数与从 1 起算的名次。
5. `PostRecallPipeline` 按组合根的步骤列表处理候选。默认 RRF 按子块 ID 合并：`score = Σ 1/(60 + rank)`，同一路重复候选只计最佳名次；再按最终子块顺序聚合父段，以最佳子块的位置确定父段排序；最后取 top_k 个父段。
6. `ContextReader` 按选定父段顺序批量读取全文、来源和命中子块定位，读取时再次应用 Scope。它不再负责融合、父段聚合或排序，也不读取未命中的子块列表。

召回不依赖预处理器或调用方提供的主题分类；正文相关性和来源／向量空间范围决定候选。可见范围在来源层控制。

关键词实现见 [KeywordRetriever](../../retrieval/keyword.py)，分词函数可通过构造参数替换，文档与查询始终复用同一分析器；仅影响关键词路，不改写向量路输入。BM25 默认 `k1=1.5`、`b=0.75`，使用正值 IDF `log(1 + (N-df+0.5)/(df+0.5))`，单篇或高频词也可召回。统计语料是本次 Scope 允许的全部子块，不能在统计前预截断，内部资料不影响普通用户的分数。父段标题已在 `retrieval_text` 中，不另加固定标题分或短语分。

当前每次查询重新分词和评分，不增加索引表、缓存或迁移；导入更新／删除后，关键词路立即读取新内容。更换关键词分析器无须重算向量，文档更新仍走原有编码与保存流程。后续实测扫描成为瓶颈时，替换为持久化倒排索引或支持 BM25 的数据库实现，保留 `KeywordRetriever.search(query, scope, limit)`、Candidate 和 Scope 边界。索引与查询复用相同分析器，更新／删除须同步索引；不能直接把 PostgreSQL 原生 FTS 排名视为 BM25。跨权限语料的词频统计变化须单独验证。

向量门槛默认关闭，非空库可能对弱相关问题也返回近邻；分数仅代表排序，不能解释为事实置信度。最终无父段返回 `no_result`；Embedding 故障明确返回 502，不自动退化成关键词查询或伪造空结果。

`Retriever.search(query, scope, limit)` 可新增或替换召回路线；召回器声明唯一 `name`，输出的 `ranks/route_scores` 使用该路线名。`MultiRouteRecall` 构造时拒绝空名称和重复名称。`RRFFusionStep` 复用 `RRFRanker`；分组、截取和未来过滤／重排通过同一个步骤协议编排。

### 5.2 路线门槛与分数

保留 JSONB + Python 精确余弦作为小规模基线，不依赖新的向量数据库。归一化向量的点积与余弦排序等价，不因参考项目使用 dot 就更换度量。后续需要规模化时，替换 `VectorRetriever` 为 pgvector 等实现，保留 `Retriever.search(query, scope, limit)` 和 Scope 预过滤边界；数据库迁移与近似召回质量另行验收。

| 路线 | 门槛规则 | 服务配置与默认值 |
| --- | --- | --- |
| 向量 | 未设置时不额外过滤；设置后仅保留 `cosine >= min_cosine` | `RETRIEVAL_MIN_COSINE`：未设置／空值为 `None`；其他值须有限且在 `[-1, 1]` 内 |
| 关键词 | 始终要求 `BM25 > 0`；同时要求 `BM25 >= min_bm25` | `RETRIEVAL_MIN_BM25`：默认 `0.0`，须有限且非负 |

门槛在各召回器内生效：先应用 Scope，计算原始分数，再过滤、取本路 top-N、生成从 1 起算的本路名次。BM25 统计仍覆盖完整可见语料。门槛是服务配置，不新增查询请求字段；默认值保持现有行为。阈值用真实问题和无关问题校准，不预设通用推荐数值。

余弦计算对绝对误差不超过 `1e-12` 的 `±1` 近似值归到端点，避免非轴对齐的同向向量因浮点误差被 `min_cosine=1` 排除。其余分数仍按实际计算值比较，该容差不是相关性阈值。

两路过滤独立，不在融合后把向量门槛应用到关键词候选。向量全部被过滤时，精确型号／错误码仍可通过关键词路线进入 RRF；默认流程中两路都为空才返回 `no_result`，自定义过滤步骤也可使最终结果为空。BM25 大于零和返回 `found` 仍不等于有可靠答案；不以统一 RRF 门槛代替相关性评估。

内部 Candidate 包含 `evidence_id/context_id/score/ranks`，并保留：

- `route_scores: dict[str, float]`：例如 `{"vector": 0.72, "keyword": 3.1}`，记录真实召回的路线原始分数；未命中的路线省略。
- `score_kind: str`：当前 `score` 的含义，例如 `cosine`、`bm25`、`rrf`，未来可为 `rerank`。`score` 仍用于当前步骤排序，不能跨不同类型直接比较。

RRF 合并路线原始分数与名次，仅将当前 `score` 改为 RRF 分数，`score_kind` 改为 `rrf`。同一路重复候选采用最佳名次及其对应原始分数，不能独立拼接不匹配的名次和分数。后续步骤保留这些溯源字段；过滤后不重写原始路线名次。分数仅存在查询内存和结果中，不新增 SQL 表或检索日志系统。

### 5.3 可编排的召回后处理

采用轻量的顺序 Pipeline：独立收集各路结果后，执行组合根注入的有序步骤列表。插入、移除可选步骤或调整兼容步骤的顺序，只修改该列表；新增处理能力实现同一个步骤协议，不改 `retrieval.service` 主循环。不引入 Haystack、DAG、动态脚本加载或数据库流程配置。

权限生成和 Scope 预过滤仍在召回前固定执行，最终正文读取由受 Scope 约束的 `ContextReader` 完成。步骤是组合根注册的可信代码，须遵守候选契约，不扩大权限、改变只读查询请求或制造新证据；Pipeline 不是不可信代码沙箱。

统一传递契约如下；全部是内存 DTO，不落表：

| 对象 | 最小字段／类型 | 用途 |
| --- | --- | --- |
| `SearchRequest` | `query`、不可变 `scope`、`top_k` | 各步骤共享的只读请求，不保存模型或 ORM 实例 |
| `RouteBatch` | `routes: dict[str, list[Candidate]]` | 保留两路独立候选，尚未进行融合 |
| `EvidenceBatch` | `candidates: list[Candidate]` | 单一有序子块候选列表，供过滤或重排 |
| `ContextCandidate` | `context_id/score/score_kind/matches` | 一条父段候选及命中子块，不含全文 |
| `ContextBatch` | `contexts: list[ContextCandidate]` | 有序父段候选列表，供父段级处理或截取 |

`SearchBatch` 为三种 Batch 的联合类型。步骤协议为 `SearchStep.process(request: SearchRequest, batch: SearchBatch) → SearchBatch`；步骤同时声明 `input_stage/output_stage`，取值为 `routes/evidence/contexts`。Batch 类型对应阶段，空列表同样保持所属阶段。

候选收集遵循 `RecallCollector.collect(query, scope, limit) → RouteBatch`，默认实现为 `MultiRouteRecall`；流水线遵循 `SearchPipeline.run(request, routes) → ContextBatch`，默认实现为 `PostRecallPipeline`。`ContextReader.read(contexts: list[ContextCandidate], scope) → list[dict]` 只读取选定父段，保持流水线给出的顺序。查询服务依赖这些协议与输入／输出，不依赖具体步骤类。

| 步骤 | 输入 → 输出 | 本次改造责任 |
| --- | --- | --- |
| `RRFFusionStep` | routes → evidence | 包装现有 RRF，按子块 ID 去重和融合，保留原始路线分数 |
| `GroupParentsStep` | evidence → contexts | 按 `context_id` 聚合；以排序中最佳子块确定父段位置与分数，不累加同父段所有子块 |
| `TopKParentsStep` | contexts → contexts | 最后按请求 top_k 截取父段，不能提前用 top_k 截断子块 |
| 自定义子块过滤／重排步骤 | evidence → evidence | 预留协议接入，不内置特定过滤策略或模型 |
| 自定义父段处理步骤 | contexts → contexts | 未来可加入父段级过滤或重排，本次不实现 |

默认步骤在 [config/components.py](../../config/components.py) 构造；未来扩展步骤仍通过同一个列表接入：

```text
默认：
[RRFFusionStep, GroupParentsStep, TopKParentsStep]

未来接入子块重排：
[RRFFusionStep, EvidenceRerankStep, GroupParentsStep, TopKParentsStep]

同一阶段的步骤可按目标重排：
[RRFFusionStep, EvidenceFilterStep, EvidenceRerankStep, GroupParentsStep, TopKParentsStep]
或
[RRFFusionStep, EvidenceRerankStep, EvidenceFilterStep, GroupParentsStep, TopKParentsStep]
```

默认三个步骤已实现；示例中的 `EvidenceFilterStep/EvidenceRerankStep` 尚无具体实现，不引入模型依赖。构造 Pipeline 时验证前一步输出阶段与后一步输入阶段相符，并确保起点为 routes、终点为 contexts；运行时检查每步实际返回的 Batch 类型。默认将 TopKParentsStep 放在末尾，Pipeline 最终输出也限制为 top_k，避免自定义父段步骤突破 API 数量上限。例如把子块重排放在父段聚合后应直接报配置错误；需要父段重排时实现 contexts → contexts 步骤。这里限制的是数据契约，不将整个处理链写死。

子块步骤只能保留、删减或重排本次召回的候选，并保持候选 ID、所属父段及原始分数。分组只能生成这些候选对应的父段。最终父段级步骤也只能处理已有父段。保持确定性同分排序；如果使用新排序分数，更新 `score_kind`，父段按最终子块排序继承分数。正文与引用在步骤处理完成后才批量读取，不能用步骤返回的改写文本替代库存证据。

### 5.4 重排扩展与错误边界

当前只提供步骤接入位置，不要求部署 reranker，也不实现外部命令或交叉编码器。未来优先在 RRF 后、父段聚合与 top_k 前接入子块重排；每路候选数与最终 top_k 分开，不能先返回 top_k 个子块再让模型重排。

重排适配器按同一 Scope 批量加载所需子块文本，输入查询与候选 ID／文本，输出已有 ID 的新顺序和分数；不得新增证据、改变父子归属或改写正文。现有 Candidate 不含正文，因此接入真实模型时需增加受 Scope 约束的文本读取适配器，不能仅更换 `Ranker` 就认为已完成模型接入。

Scope 查询、召回、RRF、分组或结果读取失败按现有错误契约返回，不泛化为静默跳过。未来可选模型重排失败时，由重排适配器返回进入该步骤前的候选顺序和分数，并记录一次简短日志；Pipeline 不捕获所有异常。Embedding 故障仍明确返回 502，不因增加流程扩展性改为单路降级。

### 5.5 实现清单与分步验收

下表改造已实现，不新增业务表或迁移，不改导入／预处理流程，也不默认增加重排模型。

| 文件 | 实现责任 |
| --- | --- |
| [contracts/types.py](../../contracts/types.py) | Candidate 路线原始分数与分数类型；只读请求、三种 Batch、父段候选、RecallCollector、SearchStep 与 SearchPipeline 协议；ContextReader 输入契约 |
| [retrieval/vector.py](../../retrieval/vector.py)、[retrieval/keyword.py](../../retrieval/keyword.py) | 增加可选构造参数 `min_cosine=None`、`min_bm25=0.0`；独立应用门槛并输出原始分数 |
| [retrieval/hybrid.py](../../retrieval/hybrid.py) | `MultiRouteRecall.collect(query, scope, limit)` 返回 RouteBatch；RRF 算法供独立步骤复用 |
| [retrieval/pipeline.py](../../retrieval/pipeline.py)、[retrieval/steps.py](../../retrieval/steps.py) | 前者执行有序步骤列表及阶段兼容检查；后者提供 RRF、父段分组、top_k 三个默认步骤，不内置所有未来策略 |
| [catalog/selectors.py](../../catalog/selectors.py) | 先补充结果中的原始分数与分数类型；再将父段分组移交 GroupParentsStep，ContextReader 接收选定父段及 matches，只负责按 Scope 批量装配正文／引用，不重复排序或聚合 |
| [retrieval/service.py](../../retrieval/service.py)、[api/views.py](../../api/views.py) | 查询服务生成 Scope 后调用候选收集、后处理和结果读取；API 只接线，不编排具体步骤 |
| [config/components.py](../../config/components.py)、[config/settings.py](../../config/settings.py)、[compose.yaml](../../compose.yaml) | 注入路线门槛与默认步骤列表；数值配置校验及 Docker 环境透传，非法值明确报配置错误，步骤顺序不由 HTTP 请求指定 |
| [tests/unit/test_retrieval.py](../../tests/unit/test_retrieval.py)、[tests/unit/test_keyword.py](../../tests/unit/test_keyword.py)、[tests/unit/test_pipeline.py](../../tests/unit/test_pipeline.py)、[tests/integration/test_rag.py](../../tests/integration/test_rag.py) | 覆盖门槛、原始分数、步骤增删与顺序、默认行为回归和 Scope 隔离 |

| 实施阶段 | 阶段结束后的可运行能力 | 验收标准 |
| --- | --- | --- |
| A：路线门槛与分数 | 继续用现有固定检索链；可配置独立门槛，RRF 保留并返回原始分数 | 默认排序保持不变；门槛临界值、未设置、非法配置通过；向量被排除的关键词命中仍保留；两路为空返回 no_result；原始分数穿过 RRF 与 API 正确保留 |
| B：默认后处理流水线 | API 完整运行，默认使用三个步骤；可在组合根插入或移除测试步骤、调整兼容步骤顺序 | 默认父段顺序／正文／引用与原流程一致；添加步骤实际改变结果，调换两个兼容测试步骤能验证执行顺序；阶段不兼容配置被拒绝；无候选、不同模型空间、内部来源过滤和 top_k 父段计数回归通过 |

当前 A、B 两阶段已实现，验收按表中行为执行。步骤扩展测试使用内存模型／步骤替身，不连接真实重排服务，也不声称已校准真实相关性门槛。真实门槛和后续重排质量用型号／错误码、同义表达、多机型与无关问题另行评估。

## 6. API 与错误

| 入口 | 约定 |
| --- | --- |
| `POST /api/v1/sources/` | Token + maintain_source；请求 `{source, document}`；同步返回 `{source_id, context_ids, reused}`，新建和更新均 200 |
| `POST /api/v1/search/` | Token；请求 `{query, filters?, top_k?}`；返回 `{mode: "hybrid", result_status, contexts}` |

查询示例：`{"query":"电池能用多久","filters":{"source_ids":["00000000-0000-0000-0000-000000000001"]},"top_k":5}`。`query` 最多 2000 字符；`filters.source_ids` 接受 1～50 个 UUID，省略表示不按来源过滤；top_k 默认 5，范围 1～20，计父段数。校验依据见 [contracts/query.py](../../contracts/query.py)。不保留尚无实现的 scenario、confirmed_context、preprocess 或知识类型过滤参数。

导入成功响应示例：

```json
{"source_id":"00000000-0000-0000-0000-000000000001","context_ids":["00000000-0000-0000-0000-000000000002"],"reused":false}
```

查询返回 `result_status=found/no_result`。`contexts[]` 每项包含 `context_id/key/title/text/locator/metadata/warnings/source/score/matches`：`source` 提供来源 ID、标题、URL、平台、日期及 Schema；`score` 是最佳命中子块的 RRF 分数；`matches` 只包含实际命中子块的 ID、key、分数、各路名次和定位。默认不返回父段下所有子块，也不返回子块的完整 metadata、warnings。结果组装依据见 [DjangoContextReader](../../catalog/selectors.py)。

`contexts[]` 包含 `score_kind`，`matches[]` 包含 `score_kind/route_scores/ranks/key/locator`。默认 `score` 仍为 RRF 分数；以后启用重排时表示最终排序分数，由 `score_kind` 说明含义。`ranks` 始终保留召回路线原始名次；`matches` 中出现的子块就是实际参与最终结果的命中证据。

输入未知字段或结构错误使用 DRF 400；认证失败 401，动作权限不足 403，范围外写入 404。领域或模型错误使用 `{error: {code, message}}`；配置缺失 503，模型失败／非法向量 502，意外服务异常 500。不返回 SQL、凭据或外部错误正文，不增加统一错误 Schema／OpenAPI 管理。

## 7. 分步实现与验收

以下步骤按依赖顺序构建；前三步可分别通过离线测试或隔离数据库运行验收，第四步提供完整 HTTP 服务。当前代码已包含前四步，具体来源插件留待后续实现。

| 步骤 | 可独立运行的能力 | 验收 |
| --- | --- | --- |
| 1：契约与插件边界 | DTO、Serializer、空注册表；无需数据库或模型 | 离线用例验证合法输入保真、非法结构拒绝、注册与替换行为 |
| 2：标准化存储 | PostgreSQL 三表与事务保存；通过受控测试向量独立运行 | 新建、重复导入、稳定 ID 更新、删除缺席段落、权限与回滚通过 |
| 3：混合召回 | 关键词、向量、RRF 与父段聚合；用模型替身运行检索服务 | 向量路与关键词路独立生效、过滤范围一致、RRF 次序及完整父段与引用正确 |
| 4：HTTP 闭环 | 模型适配器与两个 API；配置真实 Embedding 后可实际导入和查询 | Token 导入／查询及错误行为通过，HTTP 模型协议验证通过，`make test` 通过；真实模型另做中文同义词试查 |
| 5（后续）：来源插件 | 获准资料的连接器与具体预处理器，继续复用导入检索 | 单／多机型边界、正文保真与定位样本通过，现有导入检索回归通过 |

测试分别位于 [tests/unit/](../../tests/unit/) 与 [tests/integration/](../../tests/integration/)，命令为 `make test-unit`、`make test-integration` 与 `make test`；通用规则和完成定义见[项目测试规则](../unit-testing-guidelines.md)。固定向量和本地 HTTP 模型替身只验证工程行为；真实中文检索质量、吞吐与容量须在实际部署中验证，不在本文保存会过期的测试通过数量。

旧 S0～S6 数据表不直接映射新契约。保留历史迁移文件，`0003_minimal_rag` 只允许旧业务表为空时收敛；存在资料则中止，原库不变。当前部署使用新数据库，所需旧资料整理为 DTO 后重新导入。不对旧开发库进行隐式删除或自动迁移，不建设升级验收矩阵。

当前契约已删除子块 `knowledge_type` 与查询 `filters.knowledge_types`；旧请求携带它们会返回未知字段 400。可选章节主题可写入 metadata，不参与召回过滤；`document_schema` 继续描述输入结构和选择预处理器。升级时执行 `0004_remove_evidence_knowledge_type`，只删除该列，不重建正文、父子关系或已有向量；无需为了本次字段删除重新导入资料。旧 content_hash 保留，升级后的首次重复导入可能返回 `reused=false`，随后按新 DTO 判断复用。
