# 知识库技术选型与研究参考

本文只记录技术取舍与后续候选；当前范围见[总体需求](requirements.md)，数据、接口和验收统一见[首期技术设计](phase1/phase1-technical-design.md)。

当前选择按代码与简化需求整理。外部资料沿用 2026-09-27～2026-09-30 的调研，本次清理未重新访问平台或复现论文；固定提交描述的是该快照，不代表最新版本。论文结果不能作为本项目的质量或性能承诺。

## 1. 当前模块选型

| 模块 | 选择与理由 | 替代方案与暂不采用的原因 |
| --- | --- | --- |
| HTTP 与认证 | Django + DRF：复用 ORM、迁移、Token 和输入校验，提供导入、查询两个接口 | FastAPI 也适用，但切换需重新组合认证与数据层；当前不需要 Admin 或独立前端 |
| 存储 | PostgreSQL 三张业务表，JSONB 保存附加元数据与向量；同库约束与事务便于保证父子完整 | 文档数据库没有当前必需的独特收益；独立向量库增加服务和数据同步 |
| 导入编排 | Python 同步服务：校验 → 编码 → 一次事务保存；步骤少，失败后修正重提 | Haystack／LlamaIndex 留作复杂编排候选；Worker／Celery 需要实际异步或批量需求，不作为当前依赖 |
| 预处理扩展 | 连接器与处理器分离，Protocol + 显式注册表；统一输出 ProcessedDocument | 当前没有解析或自动分段实现。暂不部署通用解析平台，也不要求每类文档独立 Worker |
| Embedding | 兼容 OpenAI `/embeddings` 的 HTTP 适配器；本地或获准外部服务均可，业务不绑定 SDK | Qwen3-Embedding-0.6B、BGE-M3 可作实测候选；配置示例不表示模型已部署或优于其他模型 |
| 关键词召回 | jieba + 纯 Python BM25：查询与子块使用相同分词规则，保留型号／错误码；先权限过滤再统计词频，分词函数可替换 | 后续在线扫描成为瓶颈时，替换为持久化倒排索引或支持 BM25 的数据库实现；保持 `KeywordRetriever.search(query, scope, limit)` 边界，并验证索引更新与权限范围。原生 PostgreSQL FTS 排名不等于 BM25 |
| 向量召回 | JSONB + Python 精确余弦 top-N：可作为小规模正确性基线 | pgvector 可把距离计算移至数据库并按需使用 ANN；当前方案需扫描可见向量，大规模性能未验证 |
| 融合与返回 | RRF 按排名融合，不要求两路分数同尺度；子块召回后返回完整父段 | 直接相加分数需校准；融合、分组及未来过滤／重排通过统一步骤协议编排，重排不作为当前必需功能 |
| 验证 | pytest 单元测试 + PostgreSQL 集成测试；用受控模型验证契约与流程 | 真实模型另做相关性验证，不把模型替身的通过结果当作语义效果证明 |

这些取舍服务于当前“标准化导入 → 混合检索 → 父上下文返回”的范围。接口和模块边界见技术设计，不在此重复维护字段或阶段计划。

### 1.1 检索改造实现状态

- 保留 Python 精确余弦基线，支持可选最低 cosine 门槛并保留原始分数；归一化点积与余弦排序等价，无需为更换数学度量引入新数据库。规模化时替换 VectorRetriever 为 pgvector 等后端，保持 Retriever 与 Scope 边界。
- 向量和关键词独立应用门槛，然后用 RRF 合并各自候选；不要求关键词命中也通过向量门槛，不用 RRF 阈值代替相关性判断。
- 采用自定义顺序 Pipeline + 统一步骤协议 + 组合根有序列表，支持增删步骤和调整兼容步骤顺序；默认仅 RRF、父段聚合和 top_k。不引入通用 DAG 框架，避免小流程的额外维护成本。
- 只保留可选 reranker 接入位置，未来优先在 RRF 后、父段选择前处理子块；现有候选不含正文，模型接入需按 Scope 加载文本。重排只能处理已有候选，失败保留进入步骤前的排序。

以上检索改造已实现；内部契约、文件改动和分步验收统一见[首期技术设计第 5.2～5.5 节](phase1/phase1-technical-design.md#52-路线门槛与分数)。

## 2. 开源方案中仍值得借鉴的做法

| 方案与既有证据 | 可借鉴之处 | 当前取舍 |
| --- | --- | --- |
| [RAGFlow](https://github.com/infiniflow/ragflow/tree/313ca90f6abd7682fe8523e16fd67b3653a3fa84) | 模板化分块、复杂格式解析、混合召回和引用 | 需要现成解析与 UI 时可试用；当前只接标准 JSON，不引入完整平台栈 |
| [Dify](https://github.com/langgenius/dify/tree/725611b2e9a425519e9fcb4dcc579bafea936d27)、[FastGPT](https://github.com/labring/FastGPT/tree/b3ec46218d08a7b3e4c72e0eea7a9baebca2f736) | 将召回、融合、重排和应用编排分层 | 可作为对话应用或检索对照；当前知识库独立于 Agent 与生成模型 |
| [MaxKB](https://github.com/1Panel-dev/MaxKB/tree/bfbbffb859bf7bbebf5f83b6f4adb1de8dbfaba1) | Django、PostgreSQL + pgvector 的一体化方案 | 维护人力不足时值得用同一批样本试用；采用前核对自定义父段与接口需求 |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/65912e1bf4bcc56ac5d04fb776fc262c58f4b55d) | 多来源连接器和权限同步 | 当前少量来源不需要完整企业接入体系，保留连接器与内容处理分离的思路 |
| [Haystack](https://github.com/deepset-ai/haystack/tree/8a5406eea71a0fc19e94c4b9a5cd96df2158a45a)、[LlamaIndex](https://github.com/run-llama/llama_index/tree/169e450aa54d26ed3e0536b1a0f1ea537871aa5d) | 组件化导入与检索；Haystack 的 [DocumentJoiner](https://github.com/deepset-ai/haystack/blob/8a5406eea71a0fc19e94c4b9a5cd96df2158a45a/haystack/components/joiners/document_joiner.py) 可参考 RRF | 当前直接组合 Python 模块；复杂分支或组件复用成本上升后再评估框架 |
| [LightRAG](https://github.com/HKUDS/LightRAG/tree/453dce83d6d0354a06e46c8d4029a0895c4e054b)、[GraphRAG](https://github.com/microsoft/graphrag/tree/769542fbf1d8e5b4c6a8677fefc34621c87894c5) | 图与向量组合、跨文档主题关联 | 实体抽取和索引维护有额外成本；实际关联问题反复失败后再试验，不列为首期依赖 |

平台选择还需核对目标版本许可，尤其是 Dify／FastGPT 的附加条件、MaxKB 的 GPLv3 和 Onyx 不同目录的许可。本项目尚未做这些平台的本地效果或维护成本比较，不据此宣称自建优于平台。

## 3. 保留的论文线索

只保留与模型选择、父子检索及明确扩展方向有关的线索；不保留旧设计的性能门槛、搜索次数和重复论文列表。

| 研究 | 可以指导的验证 | 适用边界 |
| --- | --- | --- |
| [Qwen3 Embedding](https://arxiv.org/abs/2506.05176)、[BGE-M3](https://arxiv.org/abs/2402.03216) | 在相同中文问题、段落和权限范围下比较 dense 检索 | 不同尺寸与编码模式不能混用成绩；当前只对接文本向量接口 |
| [H-RAG](https://arxiv.org/abs/2605.00631) | 比较子块命中后聚合父段、再做父级重排的收益 | 其任务、模型与语料不同，不能据此确定笔记本评测父段的最佳长度 |
| [Parser, Chunking, and Embedding Interactions](https://arxiv.org/abs/2609.31660) | 解析、分块、标题前缀与模型要联合做定向消融 | 研究基于少量英语法规文档，不代表中文维修资料效果 |
| [Utilizing Metadata for Better RAG](https://arxiv.org/abs/2601.11863) | 比较少量标题／型号前缀与不加前缀的效果 | 财报领域结果不支持复制全部 metadata；当前仅编码父段标题与子块正文 |
| [Structure-Aware Chunking for Tabular Data](https://arxiv.org/abs/2605.00318)、[FT-RAG](https://arxiv.org/abs/2605.01495) | 后续处理配置表时保留表头、单位、行列关联与周围条件 | 表格化记录实验不等于扫描图片 OCR；当前没有自动表格处理 |
| [Late Chunking](https://arxiv.org/abs/2409.04701) | 长文编码后再按 token 表示池化，作为长文召回候选 | 需要兼容模型和池化方式，不能给任意 Embedding HTTP 服务加开关实现 |
| [PAGE-RAG](https://arxiv.org/abs/2608.29753) | 多跳问题中试验对已召回候选建立临时关系结构 | 不能找回从未召回的事实；额外计算成本与维修适用性需验证 |
| [ORDER](https://arxiv.org/abs/2609.17012) | 后续比较固定混合检索与按问题类型选择策略 | 训练规模与领域有限；当前只在总体需求保留场景策略，不实现自动路由 |

其他长期参考：[Ragas](https://arxiv.org/abs/2309.15217) 的评估分层、[LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 的主题资料组织模式。Wiki、Spec 与自进化的优先级以总体需求为准，不因此恢复审核发布或知识生成子系统。

## 4. 何时重新选型

| 已观察到的问题 | 优先比较的方案 |
| --- | --- |
| JSONB 扫描成为查询瓶颈 | [pgvector](https://github.com/pgvector/pgvector/tree/7db2345ed99bc77bf33cbdc8b12bd1973210dc81) 的精确查询，再比较 ANN；记录过滤后召回差异 |
| 中文词项漏匹配，或在线分词／BM25 扫描成为瓶颈 | 先验证领域词典，再比较 [PGroonga](https://pgroonga.github.io/)、分词 + PostgreSQL FTS 或数据库 BM25；索引与查询分析保持一致，原生 FTS 排名不等于 BM25 |
| 需要独立扩容或多向量表示 | [Qdrant](https://github.com/qdrant/qdrant/tree/6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de)；同时核算权限过滤、数据同步与运维成本 |
| 候选相关但前几名排序差 | RRF 参数与可选 reranker 对照，确认质量改善足以承担延迟 |
| 实际出现复杂 PDF／图片资料 | [Docling](https://github.com/docling-project/docling/tree/2d5c590c34b6378fd8a47c65b534b280aa40c93c) 等格式解析器，经预处理插件输出统一 DTO |
| 同步导入耗时影响实际使用 | 在现有导入服务外增加任务执行；任务调度与文档类型策略分离 |

用同一批获准样本比较关键词、向量和 RRF；覆盖型号／错误码、同义表达、多机型、表格、内部资料和无相关资料的问题。记录前 k 个父段的有效命中、上下文完整性、延迟、子块数量和模型配置。当前向量路没有相关度阈值，非空库返回近邻不代表问题有答案。

一次改变一个因素，保留独立验收样本。尚未用真实 IT 侠语料验证的中文质量、吞吐与容量应明确标注，不沿用历史方案中未确认的百分比或 P95 门槛。
