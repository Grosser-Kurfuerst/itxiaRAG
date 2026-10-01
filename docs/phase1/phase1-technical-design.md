# 首期技术设计：最小混合检索知识库

本文件按当前简化决定重写，替代原 S0～S6 的审核、发布和任务恢复设计。目标是：**接收已整理的文档，保存父子内容，关键词与向量混合召回，经 RRF 排序后返回完整父上下文**。知识库不生成最终答案。

## 1. 系统边界

当前输入是标准化 JSON，不是公众号 URL、HTML 或 Markdown 原文件。维护者或外部程序负责获取获准资料、脱敏、整理正文和指定父子关系。系统不调用解析器，不自动划分父子段落，也不使用 LLM 识别文档类型或改写查询。

保留 Token 认证、`maintain_source` 维护权限、`read_internal` 内部资料权限；文档范围仅为 `visibility=public/internal`。公开指对已认证普通调用方可见，不开放匿名接口。Embedding 可连接本地或获准的外部服务。

不实现审核、自动放行、系统发布账号、构建切换、撤回、审计、任务队列、retry/resume、健康探针、维护模式、生成模型、反馈或知识图谱。失败直接返回错误，修正后重新提交。

## 2. 模块与依赖方向

```text
api → contracts（校验、DTO） → ingestion.pipeline
                                  ├─ EmbeddingProvider → HTTP 模型适配器
                                  └─ DocumentStore → PostgreSQL

api → retrieval.service → HybridRetriever
                           ├─ KeywordRetriever → PostgreSQL
                           ├─ VectorRetriever → EmbeddingProvider + PostgreSQL
                           └─ Ranker（默认 RRF）
                        → ContextReader → 完整父段、来源、命中与引用

未来：SourceConnector → RawDocument → DocumentPreprocessor
                                  → ProcessedDocument → 现有导入入口
```

| 模块 | 责任 | 不负责 |
| --- | --- | --- |
| `contracts/` | DTO、Protocol、导入和查询 Serializer | ORM、模型调用和解析实现 |
| `ingestion/` | 校验 → 编码 → 保存；预处理插件注册表 | 获取推文、解析或划分段落 |
| `embeddings/` | HTTP 编码适配器、批次顺序与向量校验 | 数据库和召回排序 |
| `catalog/` | 三张业务表、事务保存、可见范围、父段读取 | 模型供应商协议、审核发布 |
| `retrieval/` | 关键词／向量召回、RRF、结果组装 | 导入与文章清洗 |
| `config/components.py` | 组合根，选择和注入具体适配器 | 业务规则 |
| `api/` | 两个 HTTP 入口、认证、输入校验和响应 | 另写一套导入或检索逻辑 |

采用轻量的端口与适配器、策略模式和依赖注入，不给所有 ORM 操作套通用 Repository。只隔离确实会变化的文档保存、Embedding、召回、排序、上下文读取与预处理。

## 3. 标准化文档与预处理插件

### 3.1 数据契约

`contracts/types.py` 是内部协议依据，`contracts/serializers.py` 是输入校验依据。JSON 样本见 `fixtures/iteration1/basic.json`。

| DTO | 字段与含义 |
| --- | --- |
| `SourceSpec` | `source_type` 来源渠道；`canonical_locator` 渠道内稳定键；`visibility` 可见范围；`source_url` 原文地址 |
| `RawDocument` | `content` 原始字节；`media_type` 格式；`metadata` 采集元数据，仅供未来插件使用 |
| `ProcessedDocument` | `title`、`document_schema`、`schema_version`、`source_date`、`metadata`、`warnings`、`contexts` |
| `ContextDraft` | `key` 文档内稳定父段键；`title`、`body` 完整上下文；`locator` 原文定位；`metadata` 适用对象等附加信息；`warnings`；`children` |
| `EvidenceDraft` | `key` 父段内稳定子块键；`body` 检索正文；`knowledge_type` 知识类型；`locator`、`metadata`、`warnings` |

数组顺序就是段落顺序，数据库保存为 `ordinal`。父子 key 在各自范围内唯一；正文非空，子块正文必须能在所属父段中找到。不自动补父段、生成摘要或拆段。Markdown 正文原样保存，包括行尾双空格。

`source_type` 表示平台，`document_schema` 表示内容类型，两者独立。例如同为 `yuque`，可以是 `repair_case` 或 `concept_note`。Schema 和知识类型接受规范化名称，不为每种文章增加表；类型专有字段放 `metadata`。可见范围只存在来源上，插件不能通过 metadata 改变权限。

### 3.2 插件接入方式

- 连接器遵循 `SourceConnector.fetch(locator) → RawDocument`，同一语雀连接器可服务不同内容类型。
- 预处理器遵循 `DocumentPreprocessor.process(raw) → ProcessedDocument`，自主选择规则、格式解析或未来的模型方法。
- `PreprocessorRegistry.register(schema, version, processor)` 显式注册策略，`process(raw, schema, version)` 调用并校验产物。空注册表拒绝处理，重复注册报错。
- 未来在 `config/components.py` 注册实现，由来源导入入口选择 Schema。插件输出仍须通过公共 Serializer 校验；不能让请求提供 Python 路径或任意加载代码。
- **本轮只有协议、注册机制和合约测试，没有具体预处理器，也没有原文导入 HTTP 入口。**当前 API 直接接收 `ProcessedDocument`。接入未来插件后，处理结果继续交给 `import_processed`，不改写存储与检索。

第一种笔记本评测插件未来按“一台笔记本一个父段，多台分开”生成 DTO；这不是所有文档的固定划分模式。

## 4. 存储设计

三张业务表，另有 Django 认证依赖表：

| 表 | 主要字段 | 用途 |
| --- | --- | --- |
| `knowledge_source` | UUID、source_type、canonical_locator、source_url、visibility、title、source_date、document_schema、schema_version、metadata、warnings、content_hash、embedding_space、时间戳 | 一份来源的当前文档与出处；`(source_type, canonical_locator)` 唯一 |
| `context_unit` | UUID、source 外键、key、ordinal、title、body、locator、metadata、warnings | 完整父上下文；`(source, key)` 唯一 |
| `evidence_unit` | UUID、context 外键、key、ordinal、body、retrieval_text、knowledge_type、locator、metadata、warnings、embedding | 召回子块及其向量；`(context, key)` 唯一 |

一个子块对应一个 embedding，编码文本固定为 `父段标题 + 换行 + 子块正文`。父段不单独编码。文档级 metadata 用于保留来源信息，不投影为召回条件，也不默认完整发送给调用方；父段与子块 metadata 随结果返回。

保存采用 `DocumentStore.save(...)` 协议，默认 `DjangoDocumentStore`。现阶段向量保存在 PostgreSQL JSONB 数组；`VectorRetriever` 在数据库完成范围过滤后逐批读取向量，用余弦计算精确 top-N，不预截断候选。复杂度约 `O(N × D)`，适合小规模验证；无 ANN 索引，不承诺大规模性能。需要规模化时替换为 pgvector 字段和 Retriever，DTO、API、RRF 不变。

### 4.1 重复与更新

同一来源、规范化 DTO 内容及 embedding_space 相同，返回 `reused=true`，不增加记录。最小实现先完成编码再由存储判断复用，因此重复提交仍可能调用 Embedding；当前不增加缓存或额外预检查。

内容更新时按稳定 key 更新父子行，保留仍存在段落的 ID；删除本次输入中不存在的段落。返回 ID 指向当前内容，不承诺不可变历史引用。没有版本表、候选、发布指针或旧引用统一失效机制。

Embedding 在数据库事务外完成；全部向量有效后一次事务保存来源、父段、子块。任意写入失败回滚本次写入，已有文档保留。这个事务用于防止半份文档，与版本发布流程无关。正常导入返回 HTTP 200；没有持久任务状态。

### 4.2 配置身份

模型地址、模型名、维度、显式 revision、查询指令和编码模板共同生成 `embedding_space`，查询仅使用同一空间的数据。更换模型或编码方式须重新导入，不把同维度当作同模型。

RRF 的 k、每路候选数和最终 top_k 属于查询参数；修改它们不重算向量。配置放 Django settings／环境变量，不建数据库配置单例，不保留复杂 profile 管理。

## 5. 检索流程

1. 接收 `query` 原样作为检索文本，校验 `top_k` 与可选过滤条件；不做查询改写或意图识别。
2. 根据当前账号生成不可由请求扩大权限的 `SearchScope`。来源 ID、知识类型过滤只缩小召回范围；两路使用同一 Scope。
3. 关键词路保留现有 PostgreSQL 子串评分：短语、词项、标题匹配；中文连续文本按短语，支持空格分隔关键词，尚无中文分词器。
4. 向量路调用 `embed_query`，过滤同一向量空间并精确余弦排序。两路各取最多 100 个子块。
5. `RRFRanker` 按子块 ID 合并：`score = Σ 1/(60 + rank)`，每路从 1 起算；同一路重复候选只计最佳名次。同分按子块 UUID 排序。
6. 按融合顺序聚合父段，以最佳子块的位置确定父段排序；保留其命中子块及两路名次，最终取 top_k 个父段。全文、来源、定位和引用由 `ContextReader` 批量读取。

知识类型过滤限制**召回子块**；返回仍是完整父段，可能包含其他类型的邻近内容，这是上下文补全，不是类型级权限。可见范围在来源层控制。

向量没有默认相关度阈值，非空库可能对弱相关问题也返回近邻；分数仅代表排序，不能解释为事实置信度。无候选返回 `no_result`；Embedding 故障明确返回 502，不自动退化成关键词查询或伪造空结果。

`Retriever.search(query, scope, limit)` 可新增或替换召回路线；每个 Candidate 的 `ranks` 必须包含唯一的召回路线名与从 1 起算的名次，不得留空，不同路线不得重用名称。`Ranker.rank(query, candidate_lists)` 可替换融合策略，也可组合 RRF 后的重排步骤。默认只用 RRF，不接交叉编码器。`ContextReader.read(...)` 隔离候选与最终上下文保存方式。

## 6. API 与错误

| 入口 | 约定 |
| --- | --- |
| `POST /api/v1/sources/` | Token + maintain_source；请求 `{source, document}`；同步返回 `{source_id, context_ids, reused}`，新建和更新均 200 |
| `POST /api/v1/search/` | Token；请求 `{query, filters?, top_k?}`；返回 `{mode: "hybrid", result_status, contexts}` |

查询示例：`{"query":"电池能用多久","filters":{"knowledge_types":["product_spec"]},"top_k":5}`。`filters.source_ids` 接受 UUID 数组；top_k 默认 5，范围 1～20。不保留尚无实现的 scenario、confirmed_context、preprocess 参数。

输入未知字段或结构错误使用 DRF 400；认证失败 401，动作权限不足 403，范围外写入 404。领域或模型错误使用 `{error: {code, message}}`；配置缺失 503，模型失败／非法向量 502，意外服务异常 500。不返回 SQL、凭据或外部错误正文，不增加统一错误 Schema／OpenAPI 管理。

## 7. 阶段与验收

| 阶段 | 可独立运行的能力 | 验收 |
| --- | --- | --- |
| A：标准化存储 | Django + PostgreSQL；通过测试输入 DTO 与受控向量保存父子，无需模型服务 | 合约、重复导入、稳定 ID 更新、事务回滚、权限校验通过 |
| B：混合检索 | 配置 Embedding 服务，API 可完成导入 → 双路召回 → RRF → 父段返回 | 单元及 PostgreSQL 集成测试通过；HTTP 协议验证通过；使用真实模型另做少量中文同义词试查 |
| 后续 C：来源插件 | 增加已获准文章的连接器和具体预处理器，继续复用 B 的保存与检索 | 单／多机型边界、正文保真与定位样本通过；现有导入检索回归通过 |

阶段 A 的测试向量只用于存储验证，不作为可部署的语义模型。阶段 B 代码已接入可用模型服务协议，但真实模型质量与吞吐须用实际部署另行验证。

旧 S0～S6 数据表不直接映射新契约。保留历史迁移文件，新增迁移只允许旧业务表为空时收敛；存在资料则中止，原库不变。当前部署使用新数据库，所需旧资料整理为 DTO 后重新导入。不对旧开发库进行隐式删除或自动迁移，不建设升级验收矩阵。
