# itxiaRAG 文档存储与召回方案调研

版本：v0.3（同步当前构建与父上下文契约）  
调研截止：2026-09-30  
适用范围：itxiaRAG 首期及后续 P1 召回能力

> 本文是对[首期技术设计](/home/kurfuerst/Coding/nju/itxiaRAG/docs/phase1/phase1-technical-design.md)和[总体技术选型](/home/kurfuerst/Coding/nju/itxiaRAG/docs/technology-selection.md)的补充研究，不替换现有技术契约。开源项目的能力依据固定提交或官方文档，论文数字是论文作者在其数据集和协议下报告的结果。本项目尚未用真实 IT 侠语料、目标硬件和生产并发复现这些结果，因此文中的“建议”仍需通过 PoC 验证。

> **契约更新（2026-10-01）：** 本项目移除独立的 source_version 表，由 import_job 承载固定输入、构建与审核，knowledge_source.current_build_id 指向当前已发布内容；更新后旧引用失效。采用 `context_unit` 父上下文 + `evidence_unit` 检索子块的两层持久化结构，父上下文替代 `context_group_id`，查询返回 `contexts[]`，`top_k` 计父段数。笔吧评测的第一个处理策略按“一篇文章中的一台笔记本一个父段”；这只是首个 Schema 处理器的具体规则，不限制语雀、维修记录或后续文档类型。本项目建议已同步该契约；开源实现和论文结论仍按原调研截止时间及固定来源引用。

## 1. 结论

调研支持继续采用 PostgreSQL，并优先完善文档结构、父子检索和证据组装。适合 itxiaRAG 的主链如下：

```text
授权来源与本次固定输入
    → 结构解析、脱敏、类型化字段和原文定位
    → 结构感知的父段／子块与表格行投影
    → PostgreSQL 权威数据 + pgvector + PGroonga/FTS
    → 权限、当前构建、适用条件硬过滤
    → dense 与 lexical 候选按 rank 融合（RRF 起步）
    → 可选 reranker
    → 按 context_id 聚合并返回完整父上下文、警告和引用
    → 返回证据包，交给外部 Agent 生成回答
```

建议保留 Django 模块化单体、PostgreSQL 和单 Worker 的首期边界，附件按需使用私有文件卷。对于约 1000 篇资料、5 个并发和 P95 不超过 2 秒的待测目标，同库精确向量搜索可以先作为基线；当真实数据证明过滤、并发或多向量场景成为瓶颈，再把检索投影迁移到 Qdrant 等独立服务，不能一开始就让向量库承担来源与构建、审核和撤回的权威职责。

最值得立即加入 PoC 的三个机制是：

1. **父子块。** `evidence_unit` 子块用于命中，`context_unit` 父段用于返回完整正文、适用条件、警告和表头，且必须限定在同一个来源的同一 build_id 内。
2. **混合召回和精确条件。** 权限、当前构建和调用方已确认的适用条件用于硬过滤；型号、错误码等还要保留词法精确匹配。通用记录可以保留，未知条件不能自动补成硬过滤。随后融合词法与 dense 候选。
3. **结构化导入。** 保留标题路径、表名／表头／单位／原文行、产品 key 和定位信息；只把高频精确过滤字段提升为 SQL 列，其余放构建内的 JSONB，避免首期表结构失控。

近期论文支持这些方向，但没有一篇论文证明某个通用系统可直接满足本项目。图检索、查询路由、语义断言编译和 Agent 可导航知识树列为 P1/P2 研究项，必须在失败案例证明需要时引入。

## 2. 与当前项目边界的对应关系

首期资料是经授权的 TXT/Markdown、语雀导出、脱敏维修记录和获准评测文章；知识库负责导入、审核、发布、权限、检索和证据引用，Agent 和最终回答生成由外部应用负责。当前设计已有来源／导入任务／父上下文／检索子块／配置／查询记录／反馈等对象；输入在单次任务内固定，发布指针独立，重建重新取得外部内容并执行质量检查。首期正常导入自动放行，异常与新处理器样本人工复核；管理命令／API 为维护入口，Admin 可选，具体规则以技术设计为准。

因此本次调研的判断标准是：

| 标准 | 具体要求 |
| --- | --- |
| 可追溯 | 每个候选能定位到来源与构建、标题路径、行／表格位置；撤回后不能通过旧索引读取 |
| 可维护 | 文档和索引产物分层；更换分块或 embedding 能建立新构建，不覆盖旧证据 |
| 中文和型号 | 同时处理中文语义、英文型号、错误码、版本号、表格字段和日期 |
| 延迟与部署 | 首期不要求独立搜索集群或生成模型；允许在 PostgreSQL 中完成权威过滤和基线检索 |
| 证据完整性 | 命中小块后能返回足以核查的父段、表头、前提和警告，而不是只返回相似句 |
| 可验证 | 能按固定语料、配置 hash 和查询 profile 重跑，并分别测检索命中、证据覆盖、权限和延迟 |

## 3. 开源知识库系统比较

### 3.1 完整平台

以下提交在 2026-09-30 固定，避免把不断变化的主分支能力当成永久事实。

| 项目 | 公开实现中确认的做法 | 对 itxiaRAG 的价值 | 取舍 |
| --- | --- | --- | --- |
| [RAGFlow](https://github.com/infiniflow/ragflow/tree/9766c8c5483b10d923acbbf2ba5e25b14819be19) | 当前主线为 Go 服务；支持多路检索、过滤、重排和父子块。其 [`RetrievalByChildren`](https://github.com/infiniflow/ragflow/blob/9766c8c5483b10d923acbbf2ba5e25b14819be19/internal/service/nlp/retrieval.go#L1024) 按父 ID、文档和知识库聚合子块，避免跨文档混用；导入阶段为父块物化隐藏索引行并以 `mom_id` 关联子块（[源码](https://github.com/infiniflow/ragflow/blob/9766c8c5483b10d923acbbf2ba5e25b14819be19/internal/ingestion/task/indexdoc/parent_child.go#L10)）。 | 父子召回、同文档聚合和复杂文档解析值得借鉴；可作为完整平台基准。 | 官方 Docker 组合仍可能包含 Infinity/ES、MySQL、MinIO、Kvrocks、NATS 等服务；对首期文本和领域版本模型偏重。旧资料中引用 Python `search.py` 的能力不能代表当前主线。 |
| [Dify](https://github.com/langgenius/dify/tree/5e3065ec7dd5b3401efefe265d9df85ca04fc1d5) | [`parent_child_index_processor.py`](https://github.com/langgenius/dify/blob/5e3065ec7dd5b3401efefe265d9df85ca04fc1d5/api/core/rag/index_processor/processor/parent_child_index_processor.py#L155) 只对子块建立向量索引；`retrieval_service.py` 将命中的子块映射回 `DocumentSegment` 父段，并按父段聚合子块、附件和分数（[父段回填源码](https://github.com/langgenius/dify/blob/5e3065ec7dd5b3401efefe265d9df85ca04fc1d5/api/core/rag/datasource/retrieval_service.py#L589)）。 | 证明“检索细粒度、返回父段”是成熟实现模式；可借鉴候选阶段与父段阶段分离。 | DocumentSegment 可以原地覆盖，需要适配 itxia 的已发布构建产物不可原地覆盖和当前发布指针约束；需自行实现来源授权、撤回和构建 hash。 |
| [FastGPT](https://github.com/labring/FastGPT/tree/e0e826bbf4d375e7aee92cc5da893740f01d92f5) | 默认召回把多路候选、融合、重排、去重、阈值和 token 预算分开；[源码](https://github.com/labring/FastGPT/blob/e0e826bbf4d375e7aee92cc5da893740f01d92f5/packages/service/core/dataset/search/defaultRecall/index.ts#L110) 可看到阶段边界，将有效过滤集合传入向量召回，并在正文回查时再次与权限／metadata 集合相交（[源码](https://github.com/labring/FastGPT/blob/e0e826bbf4d375e7aee92cc5da893740f01d92f5/packages/service/core/dataset/search/defaultRecall/embeddingRecall.ts#L202)）。 | 借鉴检索 trace、候选去重和预算控制；中文产品维护界面可作对照。 | 领域审核、来源与构建和细粒度引用仍需评估扩展点；许可证和二次分发条件需单独核对。 |
| [MaxKB](https://github.com/1Panel-dev/MaxKB/tree/2c7c8c9f2097f48c2bf3fee6bbb2a6f422bbbe43) | Django/PostgreSQL/pgvector；`Paragraph`、问题映射和 embedding 分开保存，支持 embedding、关键词和 blend 召回（[模型源码](https://github.com/1Panel-dev/MaxKB/blob/2c7c8c9f2097f48c2bf3fee6bbb2a6f422bbbe43/apps/knowledge/models/knowledge.py#L251)、[向量召回源码](https://github.com/1Panel-dev/MaxKB/blob/2c7c8c9f2097f48c2bf3fee6bbb2a6f422bbbe43/apps/knowledge/vector/pg_vector.py#L74)）。中文词法实现包含 jieba 规则。 | 与当前栈最接近，是最值得做短期替代试用的完整平台；可用同一验收集比较开发和运维成本。 | 尚未验证其已发布产物不可变、审核发布、撤回传播、父段证据和目标 P95；GPLv3、插件及分发方式要由实施者核对。 |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/e4eb5ffb2a617763a6244db01b4b6380fe6a453f) | 面向企业连接器、权限元数据和混合搜索。 | 如果未来要同步多个企业系统，可研究其连接器和权限投影。 | 当前只有少量人工授权来源，不需要完整企业连接器体系；不能用 Lite 模式资源开销代表完整索引服务。 |

**平台结论。** 若目标是尽快交付可用 UI，MaxKB 是首个替代试用候选，RAGFlow 是复杂文档和父子检索的对照；若目标是维持 itxia 的证据、发布和撤回契约，自建当前 PostgreSQL 链路仍更可控。平台试用必须用同一批固定输入、同一权限矩阵和同一 held-out 题集，不以演示问答效果决定选型。

### 3.2 可组合、图和结构化系统

| 项目 | 关键机制 | 是否适合首期 |
| --- | --- | --- |
| [LightRAG](https://github.com/HKUDS/LightRAG/tree/453dce83d6d0354a06e46c8d4029a0895c4e054b) | KV、向量、图和文档状态四类存储；官方建议生产使用 PostgreSQL，可选图后端。[存储文档](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/docs/LightRAG-API-Server.md#L917)建议新 PostgreSQL 部署优先使用普通表的 `PGTableGraphStorage`，并将 Apache AGE 的 `PGGraphStorage` 作为另一实现；embedding 变更需要重建向量，官方提供 [向量重建工具](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/lightrag/tools/README_REBUILD_VDB.md)。 | P1 关联查询候选。实体抽取、消歧、图撤回和图后端迁移会增加运维与验证成本，不作为 P0 主存储。 |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag/tree/769542fbf1d8e5b4c6a8677fefc34621c87894c5) | 实体、社区和摘要用于局部到全局问题。该固定提交的 README 标注 maintenance mode，并提示索引成本。 | 全库主题总结可能有用；型号、错误码和流程条件优先级更高，暂不引入。 |
| [OpenSPG/KAG](https://github.com/OpenSPG/KAG/tree/fdab15b3929d2ee40dfcdd388f90233096a6afc9) | Schema 约束的领域知识图；知识与原文 chunk 双向索引，并结合图、文本、精确匹配、数值计算和推理运算。 | 适合借鉴“事实必须绑定原文和 Schema”的原则；整套 OpenSPG/LLM 编排不适合作为首期依赖。 |
| [PageIndex](https://github.com/VectifyAI/PageIndex/tree/f279431eb4e47884862961b9718df180552f417a) | 为长 PDF 建本地文档树，检索时由模型按结构遍历并保留页引用；本地 SDK 与 Cloud 的 OCR、多模态能力需区分。 | 长维修手册的 P1 实验候选；依赖模型决策，与首期“不依赖生成模型、P95 2 秒”边界不一致。 |
| [HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG/tree/398bfdc388692795c105c1b903db60031975b669) | 以关联图和记忆启发式检索支持多跳问题。 | 作为多跳研究对照；不能替代权威版本和领域条件过滤。 |

图系统共同的工程问题是：图节点和关系属于索引产物，实体抽取、合并和删除失败会造成“看起来相关但无法核查”的路径。只有当评测集证明普通父子混合召回无法覆盖跨文档关系时，才值得增加图投影，并继续把原文版本作为权威层。

## 4. 近期论文的可用结论

下面选取 2026 年 1—9 月与项目直接相关的论文，包括 9 月 28 日公开的 STITCH-RAG、9 月 22 日的 Knowledge-as-Skill，以及 9 月 15 日的 ORDER 和解析／分块联合评估。日期取自 arXiv 元数据，不表示已核验会议录用或同行评审。论文中的数据集、模型和成本与 itxiaRAG 不同，数字不能作为本项目承诺。

| 论文 | 方法和原文证据 | 工程启发与边界 |
| --- | --- | --- |
| [H-RAG at SemEval-2026](https://arxiv.org/abs/2605.00631) | 子块使用三句滑窗，混合 dense/sparse 召回后映射到父文档；作者报告在其任务的开发配置中父级重排优于只按子块聚合，最佳配置 `nDCG@5=0.4872`，最终提交为 `0.4271`。 | 支持“子块命中、父段重建、父级重排可配置”。其使用 Weaviate、bge-large、GPT-5 和多轮改写，不能直接外推到中文维修语料。本项目按 Schema 确定父段边界并验收预算；笔吧首个策略可能返回单台完整评测，论文结论不能直接决定其粒度。 |
| [Parser, Chunking, and Embedding Interactions](https://arxiv.org/abs/2609.31660) | 在 4 份印度英语法规文档、800 个由 LLM 辅助生成并抽查 10% 的问题上比较 3 parser、3 chunker 和 5 个 dense 模型；作者报告最佳组合 Recall@5 `.909`、Recall@10 `.958`，并观察到标题注入在固定 token 预算下可能挤占正文而变差。 | 分块、解析和 embedding 是交互因素；先做定向消融，不要只换更大模型，也不要默认“标题越多越好”。数据规模和语言与本项目不同。 |
| [Utilizing Metadata for Better RAG](https://arxiv.org/abs/2601.11863) | 在 25 份 SEC 10-K、4,490 个块和 120 个查询上比较 metadata 前缀、后缀、统一向量、late fusion 和 query reformulation；结构字段作为检索信号可改善其任务表现，但把 metadata 拼进正文会提高重嵌入维护成本。 | 标题、型号、年份可以进入检索表示，同时继续保留 SQL 过滤字段；不要把所有 metadata 复制到每块。先比较确定性短前缀和独立过滤。 |
| [Structure-Aware Chunking for Tabular Data](https://arxiv.org/abs/2605.00318) | 将表格拆成带键值和 token 约束的行级结构，并保留表头关联；论文在 MAUD 法律记录的表格化表示上报告 hybrid MRR 从 `.3576` 提升到 `.5945`。这类键值记录不同于对扫描 PDF 的真实表格识别。 | 配置表逐行绑定表名、表头、单位、产品 key 和日期；证据返回仍需包含表头及周围说明。论文语料和指标不能当作中文表格保证。 |
| [FT-RAG](https://arxiv.org/abs/2605.01495) | 将表格单元组织成结构图，再融合周围文本；论文构造 Multi-Table-RAG-Lib，并报告 table/cell hit 和 exact-value 指标提升。数据由多表任务和 LLM 辅助构造，属于研究基准。 | 说明表格不能简单 flatten 成普通段落；首期采用轻量行投影和精确字段，只有多表问题反复失败才考虑 cell graph。 |
| [PAGE-RAG](https://arxiv.org/abs/2608.29753) | 在候选证据上构造 query-local 临时图，以支持路径和互补证据；作者在三个多跳 QA 基准上报告 support F1 和 answer F1 提升，但总计算预算与基线不完全相同。 | 图可先作为查询时的轻量重组，不必预建全库图；检索没召回的事实无法由图恢复，故 P1 使用。 |
| [STITCH-RAG](https://arxiv.org/abs/2609.34127) | topic hypergraph、每个 chunk 的实体状态和跨同名实体的 chunk-index 链接支持多跳检索；实验使用 HotpotQA、2WikiMultiHopQA 各 1,000 题及 512 题混合集。作者明确指出混合集只有 LLM judge，且有实体链接错误、顺序敏感和约 15M token 索引成本。 | 可借鉴“保留局部实体状态而不只做全局实体合并”；论文的 spatio-temporal 是 chunk 索引关系，不是来源发布日期或版本时效。暂不作为通用图存储。 |
| [ORDER](https://arxiv.org/abs/2609.17012) | 在法国历史报刊／议会资料任务上，离线按问题簇学习分块、metadata 过滤和重排配置；在线用最近质心选择预建索引，并用路由器选来源集合。路由器训练题量只有数百，泛化尚待验证。 | P1 可用于“购买咨询／维修排障／评测比较”等静态场景路由。不要把它实现成每个请求重建索引；路由错误时必须保留安全的全局 fallback。 |
| [RAG Deserves an Index](https://arxiv.org/abs/2608.20845) | 提出 ingest-time semantic compilation：在写入阶段构建带逐字出处的 atomic claims，并将 embedding 与 provenance 视为需维护、迁移和成本核算的派生结构。论文的一个增量维护实验是合成 pilot；500 条访谈语料的 claim 结果是作者报告。 | 强化现有“来源权限和当前发布指针是权威、索引是可重建投影”的设计。首期不让 LLM 自动改写事实；可在 P1 对高频资料试验“经核验的 claim + 原文 span”。逐字出处校验只能证明引文存在，仍需检查断言是否忠实保留条件和否定。 |
| [Knowledge-as-Skill](https://arxiv.org/abs/2609.25991) | 用 `SKILL.md`、目录 `index.md` 和带 YAML frontmatter 的文档使 Agent 可发现、可导航、可自描述；WixQA 的跨工作比较作者明确称为方向性证据，服务、提示词和构建过程未统一。 | 可把知识类型、主题、来源和生命周期作为返回元数据或导航接口；不能用文件树替代数据库权限、版本和精确过滤，也不属于首期召回必需项。 |

奠基工作如 RAPTOR（递归摘要树）、Late Chunking（长文编码后再池化）和 HippoRAG2 提供了有价值的研究背景，但均不能绕过本项目的证据定位、撤回和中文模型实测。尤其是 Late Chunking 不能直接当作任意 embedding 模型的开关，必须确认模型支持长上下文和对应池化方式。

## 5. 建议的存储设计

### 5.1 来源输入与检索投影

来源输入与检索投影分开，不新增独立向量数据库作为权威层。`domain_metadata` 按当前技术设计降为可选来源输入，不再单列内容层：

| 层 | 保存内容 | 生命周期 |
| --- | --- | --- |
| 来源与任务输入 | 来源保存渠道、授权、权限及 current_build_id；import_job 保存本次正文、内容 hash、Schema、可选 domain_metadata、构建与审核 | 候选输入供重试和质量放行／复核；被替代后可清理。domain_metadata 默认 `{}`；撤回和限权立即生效 |
| 检索投影层 | 清洗文本、子块、父段、表格行、定位、embedding、词法索引、构建和模型 hash | 只查询当前已放行构建；新候选单独处理，通过后切换；旧产物可清理 |

当前由 `context_unit` 保存完整父段，`evidence_unit` 保存检索子块。公共字段遵循技术设计，不再保留另一套可选父子模型：

- 父段 `build_id` 指向 import_job；子块经 `context_id` 唯一确定构建和来源，不重复保存独立 build_id；index_profile_hash 固定构建配置。
- 非空 `context_id`、`ordinal`、`context_role`：表达“哪个小块命中、完整父段是什么”；父子关系不得跨构建，子块不再维护第二套 `context_group_id`。
- 子块 `retrieval_text` 与原文正文分开：前者含确定性身份／条件前缀用于检索；父段 body 和子块正文保留授权内容，响应 text 由父段及必要范围字段确定性渲染，不把生成摘要冒充原文。
- `locator`：标题路径、行号、表格编号／行号、页码或“整理后的授权文本位置”；解析和脱敏必须保留映射。
- `structured_fields`：产品型号、版本、日期、故障码、适用范围、表头、单位等；高频和安全相关字段要有类型校验。
- `embedding_model_revision`、维度、归一化、词法分析规则和 tokenizer 版本：全部进入 `IndexProfile` hash，变更只产生新构建。

每次更新或索引重建都创建 import_job，id 即 build_id；任务输入固定，跨任务不要求长期保存原文。查询捕获配置 hash 与当前构建，返回前复核权限和发布状态。详情只展示当前构建，替换后旧引用返回 404；反馈通过最小 QueryRecord 保留来源和构建关联，不依赖旧正文。

### 5.2 文档和表格的导入投影

P0 采用确定性步骤：解析 → 清洗／脱敏 → 标题和结构识别 → 类型化字段校验 → 父段划分 → 子块切分 → 词法和向量投影 → 质量检查。复杂 PDF、OCR 和多模态解析按需引入 [Docling 文档树](https://docling-project.github.io/docling/concepts/docling_document/)；其 [HybridChunker](https://docling-project.github.io/docling/concepts/chunking/) 的结构加 token 约束可以作为分块参考，但不要求首期部署 Docling。

建议的文本规则：

- 标题路径、型号和年份使用短、确定性的前缀；通过消融实验确认是否挤占 token，不默认复制整份 metadata。
- 一个步骤链、前置条件、警告和结果尽量落在同一父上下文；过长时以子块检索、父段返回解决，而不是打散警告。具体父段边界由 Schema 处理器决定；笔吧评测第一个版本按一台笔记本划分。
- 表格行至少带表名、表头、单位、产品／配置 key、日期和原文行定位；数值、版本和型号优先走结构化字段或词法匹配。
- 解析失败、图片未识别和字段未知要保留状态；不得用导入时间补写未知的原始日期，也不得用模型生成内容覆盖授权正文。

人工补录的角色、警告、冲突标记和分组如果会影响证据生成，也须写入本次固定输入并记录依据，不能只改索引行。外部源重新导入不会自动恢复本地补录，维护者需重新提供；人工来源应保留当前整理文本或自行提供备份。

[Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) 使用模型给片段补充上下文，再进入 embedding 和 BM25；这是厂商工程实验。首期的确定性标题／型号前缀只借鉴“补足局部语境”，不等于复现其完整方法或效果。

P1 可以对访问量高且稳定的资料试验“带逐字 source span 的原子事实”，但每条事实必须能机械回指原文并保留来源与构建。没有出处校验的 LLM 摘要只能作为非权威检索辅助，不能进入证据正文。

### 5.3 一个适合 IT 侠资料的例子

以下是存储结构示例，不是实际维修建议：一篇教程包含“适用系统 → 前置检查 → 操作步骤 → 停止条件”，其中步骤很长。如果全部嵌入成一个大块，具体故障词可能被稀释；如果每句独立切分，命中步骤又可能漏掉停止条件。可以将完整分支作为父段，子块分别用于匹配症状和操作，返回时带上该分支的前置检查和停止条件，各部分保留自己的原文位置。

配置表同理：检索项可以是“示例机型 A／2026／内存 16 GB／价格 5000 元／报价日期”，原文证据仍是对应表格行及表头、单位和价格说明。比较预算时使用已核验的数值和日期字段；向量只帮助找到相关配置和说明，不执行精确数值判断。

### 5.4 与现有技术设计的差异

研究时设计已包含来源与检索分层、类型化 JSONB、父子检索、混合检索、重排和构建 hash；当前技术设计已明确 `context_unit` 父上下文、`evidence_unit` 子块，并将 domain_metadata 降为可选来源输入。下述对照用于说明研究提供的**实现和验证**依据，最新字段与接口以技术设计为准：

| 项目 | 当前基础 | 值得明确的增量 |
| --- | --- | --- |
| 证据上下文 | 已定义 context_unit、子块外键、警告和定位 | 验证按最佳子块排序聚合、父段完整返回及前提覆盖 |
| 表格 | 已保存结构字段和定位 | 行投影需要继承哪些表头、单位、产品 key；超长行如何分块 |
| 元数据 | 已区分权威 JSONB 和检索投影 | 哪些字段进入短前缀，哪些只做过滤；用消融确定模板 |
| 物理存储 | context_unit + evidence_unit 共用构建边界；早期 5 张、完整首期 7 张业务表 | 验证父子外键、当前引用、旧引用失效、重试、撤回和恢复；不再为每种来源单独建表 |
| 验收 | 已有 Top5 和关键证据完整性目标 | 增加分块前后的定位匹配与表头／警告覆盖对照，区分命中粒度和返回粒度 |

当前方案将父段作为独立 `context_unit` 存储，子块通过 `context_id` 引用；父段正文不在查询时临时重建，也不与另一套组关系并存。跨多个子块返回时，API 使用 `contexts[]`，保留 `evidence_id` 引用和 `top_k` 的父段计数语义；父段完整正文只返回一次，预算不足时整段跳过并标记。

## 6. 建议的召回链路

### 6.1 在线流程

```text
请求身份 + 原始 query + 已确认条件
  → 捕获 QueryProfile/IndexProfile
  → 构造 SearchScope（可见性、当前发布构建、succeeded、approved build）
  → 已确认适用条件过滤（型号、错误码、版本、日期、知识类型；保留合适的通用证据）
  → lexical top-k       dense top-k
             \          /
              rank 融合（RRF）
                     → 去重、候选 trace、可选 reranker
                     → 按 context_id 聚合，最佳子块决定父段顺序
                     → 读取完整父段（含表头、前提和警告），复核类型与长度预算
                     → 权限／撤回／当前构建二次复核
                     → contexts[] 与父段／子块引用定位
```

具体建议如下：

1. **先做 SearchScope。** 来源状态、发布指针、可见性、放行状态和 `build_id` 在候选产生前作为同一组条件；内部资料不能依赖请求体中的 `role`。在查询返回前再次复核撤回和读取权限。
2. **dense 和 lexical 各自保留 rank。** pgvector 官方文档指出精确搜索提供完美的向量近邻召回，而 HNSW/IVFFlat 是速度与近似召回的权衡；带过滤的 ANN 可能先扫描不足候选，需按其文档评估 iterative scan、部分索引或分区。首期先用精确搜索建立业务基线，不把“向量 perfect recall”误写成“有效证据 100% 命中”。
3. **用 rank 融合，不直接比较分数。** 不同 embedding、词法和 reranker 分数不在同一尺度；按技术设计第 5.3 节，先按各后端／模型阈值筛选相关候选，再以 RRF 融合排名。候选、分数、模型和耗时要写入 Trace。
4. **重排必须可关闭。** 只对通过权限和外发许可的有限候选重排；超时、非法 ID、重复 ID 或不可用时回退融合结果，并记录降级原因。没有真实收益时不要为首期增加模型服务。
5. **按父上下文聚合。** 子块的最终排序映射到 `context_id`，父段按最佳子块排名排序，不按命中子块数加权；完整父正文只返回一次；matched_evidence_ids 标识实际命中，citations 列出完整返回内容涉及的子块，包含未命中但随父段返回的子块。
6. **明确“无证据”状态。** 内部 Trace 区分相关性不足、条件冲突、当前构建过滤和后端失败；对外沿用既定业务／执行状态，区分证据不足和检索降级，不向无权调用者披露被过滤或撤回资料是否存在。

### 6.2 首期参数不是最终答案

沿用技术设计中每路默认 30 条作为第一组基线，并在 PoC 中比较 `top-k=20/30/50`；词法和 dense 可各取相同候选量，融合后候选上限可比较 20/40。内部候选数按子块计；对外默认 `top_k=5`，表示最多 5 个完整父段，总预算含正文及引用元数据。这些数字不是上线承诺。应在开发集调参，并用未参与调参的独立验收集报告结果：

- 内部子块候选量与对外父段 top_k 对关键证据召回和 P95 的影响；
- 递归／固定分块与结构化父子块的差异；
- 有无标题／型号短前缀；
- dense、lexical、RRF 和 reranker 的增量收益；
- 当前最佳子块排序与未来父级重排等候选策略的差异；后者仅作实验，不替代当前契约；
- 仅返回命中句与补全表头／警告时的证据覆盖和 token 成本。

### 6.3 何时升级检索后端

| 方案 | 适合的情况 | 对本项目的决定 |
| --- | --- | --- |
| PostgreSQL + pgvector 精确搜索 + PGroonga | 数据量适中，需要来源、权限、版本与检索在同一数据库处理 | 首选基线；中文 FTS 替代方案必须先预分词，并验证型号、符号和错误码。PGroonga／FTS 的词法排序不应一概称为 BM25 |
| pgvector HNSW | 精确搜索已实测影响延迟，愿意接受和测量近似召回损失 | 先于拆出独立服务评估；检查强过滤下候选不足，并与精确结果对照 |
| Qdrant 混合／多阶段查询 | 需要独立扩容、多个向量表示或更复杂的候选与重排流水线 | 官方 Query API 支持 prefetch、RRF/DBSF 等组合；只有收益明确再迁移检索投影，来源／权限仍以 PostgreSQL 为准 |
| 文档树／关系图 | 多跳关系或长手册导航确实是主要失败类型 | 作为补充索引，不代替当前精确字段、原文引用和权限过滤 |

容量评估应记录**当前及历史构建的证据单元总数**，不能只记录文档篇数。向量占用、索引构建时间和查询延迟受分块数量、维度、版本保留和过滤选择性共同影响。新增独立检索服务还意味着发布、删除和索引同步需要明确的一致性与修复机制。

## 7. 分期和可执行 PoC

### P0：在现有设计上验证主链

固定脱敏语料版本集合、embedding 模型和权限矩阵。不同分块／模板使用不同的 `IndexProfile` hash，并以原文位置作为共同标注依据；比较融合或重排时固定索引构建。建立三类对照：

| 对照 | 目的 |
| --- | --- |
| 固定／递归小块 + dense | 便于归因的简单对照，不替代既定混合检索方案 |
| 结构感知父子块 + dense | 验证命中粒度与证据完整性 |
| 结构感知父子块 + lexical/dense/RRF | 验证型号、错误码和口语问题的互补性 |

在入围方案上再开关短 metadata 前缀和 reranker，并单独运行 lexical-only 对照，避免把词法本身的贡献误归因于融合。检查少量入围组件组合即可，不对所有 parser、chunker、模型做无约束全排列。沿用技术设计中至少 60 个脱敏代表问题、常识／购机／维修各不少于 15 题的起点，再覆盖型号／版本精确题、故障排障题、评测比较题、表格配置题、无答案／冲突题，保留不参与调参的独立验收集并报告各类题量。

验收指标至少包括：

- 父段 `Hit@5`：前 5 个父段至少含一个有效依据的题目比例；另报父段 Recall@5／MRR 和可选 nDCG@5。标准依据以来源、固定评估输入的 content_hash 和原文位置标注，子块指标单独统计，不与旧子块 Top5 混比；
- **evidence coverage**：父段是否同时含前提、步骤、警告和结论；这不同于向量近邻召回；
- 引用有效率：每个返回定位是否能在独立保存的固定评估输入中复核；
- 权限／撤回负例：内部、撤回和被替代构建不能泄露；
- P50/P95、索引构建时长、embedding 调用量和存储量；
- 与需求中的 Top5 有效证据命中率 90%、P95≤2 秒和 5 并发目标的差距。

### P1：只针对已观察到的失败引入增强

- 维修流程跨段或跨文档仍断链：试验跨父上下文的关联查询、query-local 证据图或 LightRAG；保留原文定位和失败回退。
- 多种问题类型互相污染：试验静态 query routing（ORDER 思路）或不同 `QueryProfile`，路由失败时回到全局安全配置。
- 表格值反复错配：增加行级结构和 SQL 精确字段；只有多表、多跳问题仍失败才试验 cell graph（FT-RAG 思路）。
- 高频稳定资料需要更短上下文：试验出处可校验的 atomic claim 或轻量摘要索引，原文仍是权威 payload。

### P1 可选导航与 P2 自进化

P1 可以把 Knowledge-as-Skill 的 `SKILL.md`、目录索引和 frontmatter 转成可选的浏览接口，与现有 M6 知识页方向衔接。P2 再把候选反馈、冲突审核和索引策略更新纳入人工批准的自进化闭环。不能因为引入 Agent 就跳过来源授权、版本和数据库过滤。

## 8. 主要风险和未验证项

1. **语言和语料差异。** 论文多使用英语、法规、HotpotQA 或合成表格；Qwen3-Embedding、BGE-M3、中文分词和维修术语的优劣尚未实测。
2. **“相关”不等于“可用证据”。** 论文常报 answer accuracy 或 passage recall；本项目还要核验适用型号、日期、警告、出处和权限。
3. **索引变更成本。** embedding 模型、维度、分块和词法分析规则均可能要求新 build；必须在任务状态中区分失败可重试、旧 build 可服务和新 build succeeded，不能清理旧向量后再声称成功。
4. **图和 LLM 抽取错误。** 实体合并、关系方向和时间含义会引入无法从原文复核的路径；任何图增强都只能是可重建投影。
5. **平台许可证和运维。** MaxKB、Dify、FastGPT、Onyx 的许可证和附加条件不同；RAGFlow 等完整栈的依赖数量也会改变备份、升级和故障边界。实施时应按实际部署和分发方式核对许可，并测量备份、升级和维护成本。
6. **尚无本项目性能实测。** 本报告没有部署上述系统，没有用真实语料跑 embedding、PGroonga、ANN、reranker 或并发压测；相关结论应标记为“待验证”。

## 9. 参考资料与证据索引

### 官方实现和组件

- [pgvector 官方 README](https://github.com/pgvector/pgvector)：精确／近似搜索、过滤和 iterative scan 的边界。
- [Qdrant Hybrid Queries](https://qdrant.tech/documentation/search/hybrid-queries/)：prefetch、融合和多向量作为独立服务迁移时的参考。
- [Docling Document](https://docling-project.github.io/docling/concepts/docling_document/) 与 [Chunking](https://docling-project.github.io/docling/concepts/chunking/)：文档树、provenance、结构和 token 感知分块。
- [Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)：厂商工程实验，说明上下文前缀和 BM25 的一种实践；不是论文，也不是 itxia 实测。
- 各平台固定提交见第 3 节链接；实现细节应以这些提交附近源码为准，不引用旧版本路径推断当前行为。

### 论文

- [H-RAG](https://arxiv.org/abs/2605.00631)、[Parser/Chunking/Embedding Interactions](https://arxiv.org/abs/2609.31660)、[Metadata-aware RAG](https://arxiv.org/abs/2601.11863)、[Structure-Aware Tabular Chunking](https://arxiv.org/abs/2605.00318)、[FT-RAG](https://arxiv.org/abs/2605.01495)。
- [PAGE-RAG](https://arxiv.org/abs/2608.29753)、[STITCH-RAG](https://arxiv.org/abs/2609.34127)、[ORDER](https://arxiv.org/abs/2609.17012)。
- [RAG Deserves an Index](https://arxiv.org/abs/2608.20845)、[Knowledge-as-Skill](https://arxiv.org/abs/2609.25991)。
- 背景工作：[RAPTOR](https://arxiv.org/abs/2401.18059)、[Late Chunking](https://arxiv.org/abs/2409.04701)、[HippoRAG2](https://arxiv.org/abs/2502.14802)。

### 检索摘要

本轮以公开官方来源为主，Google/arXiv 搜索用于发现候选，随后读取固定 GitHub 提交、官方组件文档、arXiv 摘要／HTML／源码。Google 搜索共 4 次（3 次成功，1 次导航失败后按 trace 重试成功），OpenCLI arXiv 搜索 1 次；另用 arXiv 官方 API 按 2026-09-01 至 2026-09-30 的标题条件获取近期候选。检索不声称穷尽全部开源系统或 2026 年论文。发现用关键词包括 `2026 September retrieval augmented generation chunking document retrieval`、`RAG table retrieval` 和 `RAG index incremental`；页面读取不计入搜索次数。项目、论文和实验结论均以正文中的官方链接和证据边界为准。
