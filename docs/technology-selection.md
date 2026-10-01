# itxiaAgent 知识库系统技术选型

版本：v0.6（简化维护与质量放行，Admin 可选）  
日期：2026-10-01  
对应需求：[docs/requirements.md](/home/kurfuerst/Coding/nju/itxiaRAG/docs/requirements.md)

> 资料检索截止 2026-09-27。本文核对了十余个代表性平台／框架和组件的官方仓库，并阅读相关组件文档、三类平台的检索源码和近期论文。没有部署这些平台，也没有取得社团实际数据做性能比较。文中的项目能力是公开实现或文档证据，论文结果是作者报告，推荐顺序是结合需求作出的工程判断。

本文记录选型理由与研究依据；2026-10-01 的修订同步工程设计，不表示重新完成了外部调研。首期数据、配置、API 与迭代契约统一见[首期技术设计](/home/kurfuerst/Coding/nju/itxiaRAG/docs/phase1/phase1-technical-design.md)，测试约定见[项目单元测试规范](/home/kurfuerst/Coding/nju/itxiaRAG/docs/unit-testing-guidelines.md)。

## 1. 结论先行

推荐建设一条**结构化解析 + 元数据管理 + 可替换查询预处理 + 混合检索 + 可开关重排 + 结构化证据返回**的知识库链路，以可组合的开源组件实现知识服务。来源片段、结构化字段、关系及查询预处理的透传接口属于 P0；智能查询预处理、M6 知识页／Spec、关联检索和模型辅助草稿属于 P1；持续提出、评估和采纳变更的自进化闭环属于 P2。Agent 开发和最终回答生成由外部应用负责，知识库内部查询理解模型按需在 P1 接入；生成模型、图数据库和全量 GraphRAG 均不作为首期依赖。

这一推荐采用以下工作假设：资料以中文文本为主，夹杂英文型号、错误码和配置表；先按需求文档中的 1000 篇资料、5 个并发查询做试测；至少有一名成员能够维护 Python 服务。资料量、服务器、GPU、模型预算和维护人力均未确认。这些条件变化时，应按第 6 节的验证结果调整选择。

### 1.1 推荐架构

```text
授权资料
  → 原生文本解析（复杂文档按需使用 Docling）
  → 规范化、脱敏、来源、构建与证据定位（外部模型调用之前）
  → 结构感知分块 + 元数据字段
  → Qwen3-Embedding-0.6B 向量 + PGroonga 词法索引
  → PostgreSQL + pgvector（元数据、权限、当前构建、向量）
  → 混合召回（dense + lexical + exact filter）
  → RRF 融合 →（可选）Qwen3-Reranker-0.6B
  → 证据包、引用查看与状态返回
  → 外部 Agent／客户端组织回答或转交志愿者
```

首期服务只需 **Web/API、单个导入 Worker、PostgreSQL**；Web 与 Worker 共用应用镜像，Python 导入模块在 Worker 进程内，PGroonga 和 pgvector 是数据库扩展，评估脚本离线运行。短文本输入保存在 import_job；有附件时按需使用私有文件卷并备份。Embedding 和可选 reranker 可以使用获准的现有服务；自托管时另计资源。Redis、对象存储服务、Langfuse、Haystack 和独立图数据库均不强制部署。

查询侧为“原始或已整理 query → 请求校验 → 查询预处理（首期透传，可主动跳过）→ 条件与权限过滤 → 混合召回 → 证据返回”。预处理位于 M5 内，不增加独立服务；后续可替换为规则或 LLM 处理器。

### 1.2 模块决策表

| 模块 | 首选技术 | 首期优先级 | 主要理由 | 主要替代与不选原因 |
| --- | --- | --- | --- | --- |
| 文档解析 | TXT/Markdown 原生解析；HTML 可先人工转为文本；复杂文件按需 Docling | P0 文本；P1 OCR 扩展 | 保留来源结构；Docling 支持本地解析、表格与结构导出 | DeepDoc、MinerU、Unstructured 均可做对照；先不为尚未确认的文件格式部署完整 OCR 栈 |
| 导入编排 | Python 模块化导入流程 + PostgreSQL 任务表 + 单 Worker | P0 | 少量依赖，步骤和领域数据模型由项目明确控制，任务状态可恢复 | Haystack／LlamaIndex 可作为后续薄编排层；首期引入会增加框架适配和依赖，不解决权限、版本和审核问题 |
| 来源与发布数据 | PostgreSQL，附件文件卷可选 | P0 | 事务、权限、当前构建、审核和来源集中管理，使用附件时独立备份 | MongoDB 也能实现，但当前需求更偏关系约束；向量库不能单独替代业务数据库 |
| 中文词法检索 | PGroonga | P0 | 在 PostgreSQL 内提供中文全文检索，避免另建搜索集群 | 预分词 + PostgreSQL FTS 可降低扩展依赖；Elasticsearch/OpenSearch 能力强但增加运维成本 |
| 向量检索 | pgvector；精确检索起步，按需 HNSW | P0 | 与权限、构建、来源表同库，便于维护一致性 | Qdrant 是首选迁移候选，但要同步元数据投影；FAISS 需另外实现服务和元数据管理 |
| 分块 | 类型化规则 + tokenizer；Docling 文档使用 HybridChunker | P0 | 保留标题、表格行、警告和适用条件；分块与 embedding token 限制一致 | 固定字符／递归切分实现简单，作为基线；能否保留步骤和表格须验证 |
| Embedding | Qwen3-Embedding-0.6B、1024 维；BGE-M3 对照 | P0 | Apache-2.0、多语言、支持任务指令和可调维度 | BGE-M3 的 dense 模式同样简单可用；若实测更好可直接替换。云 API 减少推理运维，但需核对数据授权和费用 |
| Reranker | Qwen3-Reranker-0.6B | P0 候选 | 可本地部署，对 query–证据对进一步打分；须验证收益和延迟 | 无 reranker 成本更低；较大 reranker 资源需求更高。没有可测收益时保留关闭配置 |
| 检索融合 | dense + PGroonga lexical + 精确字段过滤，RRF 起步 | P0 | 同时处理口语问题、型号/错误码和年份配置；RRF 不要求不同检索器分数同尺度 | 只用向量：容易漏掉型号和错误码；只用 BM25：难以处理口语和同义表达；复杂学习排序：需更多标注数据 |
| 查询预处理 | Python 函数／Protocol + 默认透传 + 依赖注入 | P0 接口；P1 规则／LLM | 接受原始或已整理 query，后续按统一输入输出增加意图识别、改写、候选条件提取 | 硬编码在 API 中难替换；全部绑定外部 Agent 限制普通客户端；通用工作流／插件框架增加首期依赖 |
| 知识结构 | PostgreSQL 实体／关系表；P1 按需试验 LightRAG | P0/P1 | 先表达型号、配置、症状、流程和来源关系 | Neo4j 多跳查询方便，但增加服务；GraphRAG 的全库社区摘要暂非核心需求 |
| LLM Wiki / Spec | Markdown 内容 + Pydantic/JSON Schema + 版本表 | P1（M6） | 后续可审阅、可校验地维护主题页和规范；首期只保留来源片段和结构化字段 | 首期不实现专门页面；纯提示词约束难以校验；Obsidian 不能独自承担公开服务的权限和审核 |
| 知识库对外接口 | DRF 查询、证据返回、引用查看、反馈和维护接口 | P0（M7） | 以稳定的证据协议支持外部 Agent 或其他客户端，与 M1 共用服务 | Agent 与最终回答生成由外部应用负责；M7 不适配模型，M5 可预留查询理解模型接口 |
| 管理/API | Django 5.2 LTS + DRF + 管理命令；Admin 可选 | P0 维护能力；界面按需 | 复用 ORM、迁移、认证与 API，命令即可维护；减少首期界面开发 | FastAPI 同样可做 API／命令服务，但需组合 ORM、迁移与认证；Dify/MaxKB 的证据与发布流程仍需适配 |
| 异步任务 | PostgreSQL 任务表 + 单 Worker；Celery 留作扩展 | P0 / P1 扩展 | 小规模串行导入可恢复，首期减少常驻服务 | Celery 的多 Worker、重试和调度更成熟；并行需求出现时优先采用，不自行扩展成通用调度器 |
| 评估 | 离线检索指标 + 人工评审集 + 独立 held-out 集 | P0；Ragas 后续按需 | 评估检索相关性、证据完整性、来源定位与接口行为，不依赖生成模型 | 仅看相似度无法判断证据适用性；Ragas／LLM judge 留待外部应用或后续需求，不能代替人工评审 |
| 观测 | 结构化 Trace；P1 按需接入 Langfuse | P0 / P1 展示 | 首期能还原检索、引用、耗时与成本即可 | 无关联标识的普通日志难以定位问题；独立观测平台增加部署和数据治理成本 |

权威数据层建议使用当前支持的 PostgreSQL 版本，并在部署文档中固定具体版本。本文不把数据库大版本号写死，以便在实施时结合扩展兼容性和运维环境确认。

**整体平台取舍也有成本。** 组件组合需要自行实现质量检查、异常复核入口、导入状态、引用接口和备份流程，并不一定比开箱平台更省开发时间。当前推荐基于“独立知识服务、可定制证据模型、有人维护代码”的目标；如果社团缺少持续开发人力，应先试用 MaxKB 或 RAGFlow，并以同一验收集验证，接受其已有工作流后再投入二次开发。

## 2. 调研范围与开源项目结论

### 2.1 完整平台类

| 项目 | 官方实现的主要做法 | 适用情形 | 本项目的取舍 |
| --- | --- | --- | --- |
| [RAGFlow](https://github.com/infiniflow/ragflow/tree/313ca90f6abd7682fe8523e16fd67b3653a3fa84) | DeepDoc 复杂解析、模板化分块、混合召回、重排、引用；典型自托管栈含 Elasticsearch/Infinity、MySQL、Redis、MinIO | 复杂文档多，且希望尽快获得完整 UI | Apache-2.0，可直接试用；作为完整平台对照。首期文本为主，其默认基础设施较多，领域版本／审核模型仍需适配 |
| [Dify](https://github.com/langgenius/dify/tree/725611b2e9a425519e9fcb4dcc579bafea936d27) | 可视化 Workflow、RAG Pipeline、Agent、模型管理和 API | 快速搭建对话应用，多人用可视化流程编排 | 可作为 Agent 前端候选；独立知识服务需要自行定义来源、维修案例与证据生命周期，暂不绑定其内部数据模型 |
| [FastGPT](https://github.com/labring/FastGPT/tree/b3ec46218d08a7b3e4c72e0eea7a9baebca2f736) | 多格式导入、多路召回、融合重排、引用反馈、调用日志与应用评测 | 中文知识库快速上线，对现有工作流接受度高 | 作为中文检索和交互对照；自定义审核／版本模型须评估扩展点。不是因为中文能力不足而排除 |
| [MaxKB](https://github.com/1Panel-dev/MaxKB/tree/bfbbffb859bf7bbebf5f83b6f4adb1de8dbfaba1) | Django、LangChain、PostgreSQL + pgvector，导入、切分、向量化和工作流 | 维护人力少，希望采用相对紧凑的一体化方案 | 最值得先做短期试用的替代方案之一；若现有数据模型能通过验收，直接部署可能比自建划算 |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/65912e1bf4bcc56ac5d04fb776fc262c58f4b55d) | 50+ 连接器、权限元数据、混合搜索、企业知识问答 | 多企业系统接入和复杂权限同步 | 现阶段的三类人工授权来源尚不需要这套连接器体系；其 Lite 模式不含文档索引，不能把 Lite 资源开销当完整知识库开销 |

许可证需要区别对待：[Dify](https://github.com/langgenius/dify/blob/725611b2e9a425519e9fcb4dcc579bafea936d27/LICENSE) 和 [FastGPT](https://github.com/labring/FastGPT/blob/b3ec46218d08a7b3e4c72e0eea7a9baebca2f736/LICENSE) 使用带多租户服务、前端标识等附加条件的许可证，不能简单写成标准 Apache-2.0，但附加条件也不意味着社团自用不可行。MaxKB 的 GPLv3 不禁止非营利使用，私有部署本身也不自动要求公开修改；需按实际分发方式履行义务。Onyx 的普通目录与 `ee` 目录许可不同。本文暂不选整个平台的主要原因是领域适配与维护取舍，许可证是实施时核对的条件。

### 2.2 可组合框架类

**[Haystack](https://github.com/deepset-ai/haystack/tree/8a5406eea71a0fc19e94c4b9a5cd96df2158a45a)**（Apache-2.0）提供显式、模块化的 Pipeline 和检索、路由、生成组件。它适合分别替换解析、召回、融合、重排，保留为后续可选编排层。首期步骤少且依赖领域状态，采用 Python 模块直接组合，减少框架适配。项目仍需实现或适配 PGroonga 检索器、统一证据对象和领域过滤；框架不会自动完成权限、版本及审核。

**[LlamaIndex OSS](https://github.com/run-llama/llama_index/tree/169e450aa54d26ed3e0536b1a0f1ea537871aa5d)**（MIT）的连接器、索引和检索生态同样适用；团队若更熟悉它，可以保持数据协议不变而替换编排层。首期采用 Python 模块；未来编排复杂度上升时，可根据团队熟悉度在它与 Haystack 之间选择，目前没有本地实测证明任一框架效果更好。其官方 README 现强调 LlamaParse、LiteParse、解析与抽取评测，是维护路线的观察项，不表示 OSS 已停止可用。

### 2.3 图增强类

**[LightRAG](https://github.com/HKUDS/LightRAG/tree/453dce83d6d0354a06e46c8d4029a0895c4e054b)**（MIT）采用低层/高层双层检索，把实体关系图与向量表示结合；当前实现还提供增量更新、引用、重排、删除与图重建、多种存储后端。它适合作为 P1 关联查询的试验候选，但实体抽取、消歧、来源撤回仍需验证，不能只看问答分数。

**[Microsoft GraphRAG](https://github.com/microsoft/graphrag/tree/769542fbf1d8e5b4c6a8677fefc34621c87894c5)**（MIT）的《From Local to Global》路线通过实体、社区和摘要支持跨文档主题问题；当前 README 声明主要处于 maintenance mode，并提示索引成本较高。维护状态可随时间变化，此处仅指所引提交。IT 侠优先解决精确型号、版本和条件匹配，全库社区摘要的收益尚未得到业务样本支持。

**[PAGE-RAG（2026）](https://arxiv.org/abs/2608.29753)** 提供补充思路：图可以是当前查询候选的临时选择结构，用来源和支持路径筛选证据，不必预建全库图。本文把它作为研究路线，不将论文等同于成熟产品；实验边界见第 4 节。

### 2.4 从源码提炼的可复用做法

| 已阅读的源码 | 实际观察 | 对本项目的启发 |
| --- | --- | --- |
| [RAGFlow search.py](https://github.com/infiniflow/ragflow/blob/313ca90f6abd7682fe8523e16fd67b3653a3fa84/rag/nlp/search.py#L243) | 先构造过滤条件；文本和向量进入融合表达式；另有 [模型重排](https://github.com/infiniflow/ragflow/blob/313ca90f6abd7682fe8523e16fd67b3653a3fa84/rag/nlp/search.py#L664) | 检索、过滤和重排分层，保留调整与观测入口 |
| [Dify retrieval_service.py](https://github.com/langgenius/dify/blob/725611b2e9a425519e9fcb4dcc579bafea936d27/api/core/rag/datasource/retrieval_service.py#L324) | 明确避免在混合融合前套用最终分数阈值，因为 embedding 相似度与融合／重排分数不等价 | 不跨模型、跨阶段复用阈值；先融合再标定最终拒答条件 |
| [FastGPT defaultRecall](https://github.com/labring/FastGPT/blob/b3ec46218d08a7b3e4c72e0eea7a9baebca2f736/packages/service/core/dataset/search/defaultRecall/index.ts#L98) | 多路召回、融合和重排分开；最终按 [去重、相似度、token 上限](https://github.com/labring/FastGPT/blob/b3ec46218d08a7b3e4c72e0eea7a9baebca2f736/packages/service/core/dataset/search/defaultRecall/index.ts#L172) 过滤 | 记录各阶段候选，避免重复证据挤占生成预算 |
| [Haystack DocumentJoiner](https://github.com/deepset-ai/haystack/blob/8a5406eea71a0fc19e94c4b9a5cd96df2158a45a/haystack/components/joiners/document_joiner.py#L218) | 提供基于排名的 RRF 融合 | 借鉴排名融合算法；首期无需为 RRF 引入整个框架，也不要求词法和向量分数同尺度 |

这些实现的具体顺序、融合算法和多模态支持并不完全相同；本文借鉴其分层方式，不声称它们都使用同一条 RRF 管线。

## 3. 各模块详细选型

### 3.1 数据接入与文档解析：原生文本优先，Docling 按需

**选择及理由。** P0 人工导入授权的 TXT/Markdown，其他格式先由成员整理为文本，保留标题、段落、表格和来源地址，不预设已获得语雀 API 或公众号批量抓取能力。复杂 PDF、办公文件或图片出现实际需求时，再采用 [Docling](https://github.com/docling-project/docling/tree/2d5c590c34b6378fd8a47c65b534b280aa40c93c) 的统一文档表示、布局、表格和 OCR 能力。Docling 代码为 MIT，所用模型需分别核对许可。首期可人工补录少量仅在图片中的配置，OCR 自动化列 P1。

**替代及切换条件。** RAGFlow DeepDoc、[MinerU](https://github.com/opendatalab/MinerU) 和 [Unstructured](https://github.com/Unstructured-IO/unstructured) 都值得用于复杂样本对照；未对社团样本实测，不能据其宣传认定哪个中文解析最好。Docling 暂优先是因为统一结构和本地处理符合证据定位需求；若特定 PDF 表格明显解析不好，再替换该格式的解析器，无需替换检索层。

**接入约束。** 保留内容摘要、解析器版本、来源日期及段落／页码／表格定位；未识别图片和缺失字段明确标记。来源日期未知时不能用导入日期代替。原始敏感文件限权保存，本地清理和脱敏先于任何外部模型调用；解析失败不覆盖当前构建。

### 3.2 导入编排：Python 模块化流程 + PostgreSQL 任务表 + 单 Worker

**选择及理由。** 用项目内 Python 模块组织“解析 → 清理与脱敏 → 类型化字段整理 → 分块 → embedding → 写入候选构建 → 质量检查”。模块约定输入／输出，单 Worker 依次调用，PostgreSQL 任务表记录来源与构建、状态、尝试次数、失败步骤和错误。耗时工作由 Worker 执行，不阻塞提交请求；新构建完成索引并通过自动／人工放行后再生效。首期字段由规则辅助、成员确认，缺失项保留未知。

**职责分工。** Python 模块定义处理步骤和数据传递；任务表记录任务进度及重试依据；Worker 领取并执行任务。即使不用框架，模块边界、幂等重试和发布切换仍需实现；不额外开发通用 DAG 调度器。

**可替换边界。** 用项目内函数／Protocol 隔离解析／分块、文档与查询编码、词法后端、重排和查询预处理。解析统一为带原文定位的内容块，编码统一维度、顺序和模型身份，词法后端统一候选 ID／rank 和服务端 SearchScope，重排结果必须关联原候选；超时、限流和非法输出统一为技术异常，由编排层决定重试／降级。SDK 与数据库扩展细节留在适配层，授权与发布规则留在领域服务。不为每个函数或 ORM 预建通用抽象；具体协议见技术设计第 2.5 节。

**替代及切换条件。** Haystack／LlamaIndex 作为后续可选编排框架，适合流程分支、组件复用和组合成本明显增长时引入。当前流程较固定，自行约定少量模块接口比适配框架更直接。Celery 用于任务调度，多 Worker、复杂重试或定时同步出现后再评估；它不能替代业务处理模块。Airflow/Prefect 暂不匹配小规模人工导入。

### 3.3 来源、构建与检索存储：PostgreSQL + pgvector，文件卷可选

**选择及理由。** PostgreSQL 保存来源、当前构建、审核、可见范围和父子证据。短文本输入直接存在 import_job；附件按需放入私有文件卷，数据库记录文件键和摘要，使用时一并备份。外部来源更新或重建重新取得最新内容，不以长期原文归档为前提。已有可信 S3 存储时可直接复用，首期无须另开对象存储服务。访问附件必须经过应用授权，不能把文件目录直接公开。

以下是逻辑数据分组，不要求首期按每个名词拆表：

| 数据组 | 最少承载的信息 |
| --- | --- |
| 来源与导入构建 | 原始定位、日期、授权、固定任务输入、内容 hash、审核／撤回状态和 current_build_id；仅当前构建可查询 |
| 检索与证据单元 | 独立父上下文、检索子块、原文位置与范围字段；仅子块建向量，父子经构建关联来源，继承当前发布与权限状态 |
| 领域知识与关联 | 机型配置、维修案例、术语别名；明确事实／观点／推测，字段允许未知 |
| FAQ、主题页与 Spec（P1） | 后续 M6 保存正文／结构化规范、维护者、版本、依赖证据与发布记录；首期不预建该子系统 |
| 任务、反馈与评估 | 处理状态、失败原因、关联查询／证据构建、必要的用量与评估记录 |

物理映射采用 4 张核心表 knowledge_source／import_job／context_unit／evidence_unit，加 1 张 retrieval_settings；迭代一至三共 5 张，迭代四再增加 query_record 和 feedback，完整首期共 7 张业务表，不计 Django 框架表。低频领域字段放 JSONB，别名和评估集可用版本化文件，不要求按上表逐项建表。来源访问范围只使用 `visibility=public/internal` 和服务端身份，不设逐来源授权组。

**配置分层。** IndexProfile 固定文档产物和索引，QueryProfile 固定兼容的查询策略；两者用规范化配置 hash 标识，当前配置保存在 retrieval_settings。查询调参不重建文档；更换模型／分块／索引采用停机维护，候选校验并切换后恢复服务。普通内容更新仍使用候选、原子发布和失败保旧，细则见技术设计第 4.4 节。

**向量选择。** [pgvector](https://github.com/pgvector/pgvector/tree/7db2345ed99bc77bf33cbdc8b12bd1973210dc81) 与元数据同库，减少跨库同步；先以精确向量检索建立质量和延迟基线，实测不达标再加 HNSW。Qwen 0.6B 的 1024 维向量处于当前 pgvector 的 HNSW `vector` 维数支持范围内。规模不能只按文章数判断，要记录 chunk 数、过滤选择性、并发、索引内存和查询耗时。

**替代及切换条件。** [Qdrant](https://github.com/qdrant/qdrant/tree/6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de)（Apache-2.0）支持 dense/sparse、多向量、payload filter 与融合，是需要独立向量扩展时的优先候选；代价是另运维服务并同步权限／当前构建投影。FAISS 适合离线算法试验，业务服务与元数据能力需另建；Milvus 适合有更大规模与运维需求时再评估。MongoDB 能保存灵活文档，但本项目优先使用现成的关系约束和事务。迁移由实测瓶颈触发，不规定一个未经验证的向量数量门槛。

### 3.4 中文词法索引：PGroonga

**选择及理由。** [PGroonga](https://pgroonga.github.io/) 在 PostgreSQL 内提供包括中文在内的多语言全文索引，采用 PostgreSQL license。对标题、别名和正文建立词法召回，对规范化型号、年份、错误码另保留精确字段。“R9000P 2024”“0x80070005”等信息需要保留，不能被语义相近的型号替换。PGroonga 的词法分数不应直接标为 BM25，首期通过 RRF 与向量排名融合。

**替代及切换条件。** PostgreSQL 默认全文解析不擅长未分词中文，但可在应用侧用 [jieba](https://github.com/fxsjy/jieba) 等预分词，再使用 `simple` 配置与 GIN/`tsvector`；它减少数据库扩展依赖，但需保证索引与查询分词一致，并维护硬件型号词典。若部署环境不支持 PGroonga，先试此方案；需要更成熟的中文分析器、搜索运维能力或更大规模时再选 OpenSearch/Elasticsearch。后两者是完整搜索引擎，首期额外服务与数据同步成本较高，不能仅为“BM25”这个名称引入整套集群。

### 3.5 分块与结构保留：类型化规则 + token 预算

**选择及理由。** TXT/Markdown 先由格式解析器保留标题、列表、表格和定位，再由按 Schema 选择的文档处理器生成完整父上下文 `context_unit`，在父段内切分 `evidence_unit`。子块按模型 tokenizer 控制长度并用于词法、向量及可选重排，父段独立存储、无向量，用于完整返回。首个笔吧评测策略按同一文章“一台笔记本一个父段”，测试项目只划分子块；语雀知识、维修记录等由各自处理器确定父段边界，不受笔记本规则限制。后续复杂格式可参考 [Docling HybridChunker](https://docling-project.github.io/docling/concepts/chunking/)，不作为首期依赖。型号、年份、表头、局部测试条件和警告保留原文定位，不能只依赖默认分块配置保证这些业务约束。

**论文依据。** [Structure-Aware Chunking（2026-05-01）](https://arxiv.org/abs/2605.00318) 的法律表格实验支持保留行／键值关系，但不能证明同样收益必然发生在电脑配置表。先比较类型化分块与递归分块，再决定复杂规则投入多少。

**替代及切换条件。** 固定窗口或递归切分适合作基线，若短文本已完整保留上下文，可以继续用。[Late Chunking](https://arxiv.org/abs/2409.04701) 是先编码长文档，再对 token 表示分块池化的另一条路线，需要兼容的长上下文编码器及池化方式；不能直接给采用末 token 表示的 Qwen3 Embedding 加一个开关就认为实现了原论文方法。首期不选该路线，长文召回持续不足时才单独验证兼容模型及导入成本。

### 3.6 Embedding：Qwen3-Embedding-0.6B，BGE-M3 作同级对照

**选择及理由。** 起步使用 [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)，固定 **1024 维**。模型卡列出 Apache-2.0、多语言、32K 上下文、32–1024 可调维度与查询任务指令。较小尺寸和指令接口使其适合先验证，并不代表已证明优于 BGE。query 按模型卡模板加入固定检索指令，文档编码正文及必要的标题／型号／年份；模型的最大上下文长度不是建议 chunk 长度。

**元数据选择。** [Utilizing Metadata for Better RAG（2026-01-17）](https://arxiv.org/abs/2601.11863) 在 10-K 文件上研究把元数据加入检索表示。本项目据此同时保留可过滤字段与少量正文前缀；缺失年份、配置、原因或价格不由模型补造。前缀是否改善效果仍需消融测试。

**替代及切换条件。** [BGE-M3](https://huggingface.co/BAAI/bge-m3)（MIT，1024 维，8192 上下文）可单独使用 dense 模式，部署与索引不必比 Qwen 更复杂；只有启用 sparse/ColBERT 时才需额外索引策略。真实中文维修问题上若 BGE 更好，就采用它。云 embedding 省去推理运维，但需确认内部资料的外发范围和费用；仅在获准时作为对照，不是必测依赖。

**版本要求。** 模型、维度、归一化、tokenizer 与前缀模板一起版本化；切换模型须重算文档向量并切换匹配的查询编码器，不能把两个模型的向量混入同一有效索引。CPU/GPU 的吞吐和延迟尚未实测，不能由“0.6B”推定满足在线目标。

### 3.7 重排：Qwen3-Reranker-0.6B 作为可开关候选

**选择及理由。** dense/词法分别召回并融合，先以融合后 30–50 条候选作为起始调参值，再用 [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) 对子块的 query–retrieval_text 对精排，再按 context_id 聚合，默认向调用方返回最多 5 个完整父上下文；top_k 计父段，内部候选数计子块。这些数字是起始配置，不是延迟或质量承诺。相似品牌、机型和症状可能需要精排来区分适用条件。

**替代及切换条件。** “无 reranker”必须保留为 P0 基线：如果离线集的检索命中率、MRR 和人工相关性没有稳定改善，就关闭它。4B/8B 或云端 reranker 可能更好，但显存、调用费与延迟更高；只有 0.6B 被证实不足时才升级。RRF 负责合并候选，reranker 负责候选内排序，两者不能相互替代。

### 3.8 检索融合、过滤与引用

**推荐顺序。** 权限、来源有效性和发布状态始终是 SQL 硬条件；设备／年份／系统等只在用户信息和元数据明确时作为匹配条件，未知不能推定为匹配，也不能过滤掉所有通用常识。知识服务返回缺失条件，Agent 决定是否追问。按以下步骤取证：

1. 在允许集合中并行执行 PGroonga 与 pgvector 的子块召回。
2. 用 RRF 合并，按 evidence_id 去重；复核候选的当前权限和来源状态。
3. 可选对子块重排，按 context_id 聚合；父段由最佳子块的最终排名排序，不以命中数量加分。复核完整父段的权限、类型与适用条件，再按 top_k 和 token 预算选择；预算不足时整段跳过并标记，不截断必要条件。
4. 返回 `contexts[]`：每项含 context_id、完整父正文、scope_fields、matched_evidence_ids、子块引用、来源与构建、日期、原文定位和已有警告，以及不足／冲突／过旧等状态。父子 ID 不互换，不强制存在 claim_id。

RRF 首期为默认；有标注数据和稳定指标后再比较加权融合。按当前用户可见范围获取引用视图，避免只藏原文链接却输出内部标题或摘录。

RAGFlow、Dify 和 FastGPT 的源码均体现了召回、融合、重排／过滤和 token 预算的分层；例如 [Dify 在混合召回前不使用最终阈值](https://github.com/langgenius/dify/blob/725611b2e9a425519e9fcb4dcc579bafea936d27/api/core/rag/datasource/retrieval_service.py#L324)。这支持分阶段处理，不意味着照搬平台的阈值。

**权限与召回边界。** SQL `WHERE`、应用权限和可选 RLS 决定“能否看”；HNSW 等近似索引的扫描后过滤可能影响候选是否充足，本身不等于越权。[pgvector 文档](https://github.com/pgvector/pgvector/tree/7db2345ed99bc77bf33cbdc8b12bd1973210dc81) 说明可用 iterative scans 改善过滤后的召回。先用精确检索建立基线，再判断是否需要这些参数。被拒绝的文档不能进入 reranker、生成器、公开引用或公开缓存；不能为提高召回而移除授权条件。

**为什么不用单一检索。** dense 能覆盖“电脑变慢”的口语表达，词法和精确字段能保住“2024”“4060”“0x80070005”等硬 token；两者分数不在同一尺度，故首期用 RRF。召回阈值、重排阈值和拒答策略需用真实问题集标定，不复用未经验证的默认值。

**引用约束。** 首期返回证据 ID、片段、来源、构建和原文位置；引用查看再次校验可见性及撤回状态。已标注冲突的来源保留冲突及各自条件，资料不足时返回相应状态。回答断言与证据的语义对应、追问和转人工由外部 Agent 负责，不把回答核验作为知识库接口的实现要求。

### 3.9 知识图谱与结构化关系：关系表 P0，图增强 P1/P2

**选择及理由。** P0 在 PostgreSQL 维护机型—配置、案例—症状、子块—父段—构建—来源等必要关联；来源已有流程的前提作为字段或关联片段保留，不提前建设 Spec 子系统。关系带来源与构建、证据状态、审核状态和适用条件。P1 的 F-11 再基于这些数据实现“症状 → 案例 → 已做检查 → 流程”的关联查询，优先用 SQL，不立即增加常驻服务。案例里观察到一种症状，不等于这条关系能证明另一台设备的故障原因。

**替代及切换条件。** Neo4j 多跳表达方便，但增加服务、同步与权限映射；LightRAG 已具备增量更新和引用能力，适合 P1 对照，却仍需验证抽取错误和来源撤回。GraphRAG 全库社区摘要适合跨文档主题综述，不能默认用于高风险维修步骤。PAGE-RAG 的 query-local 图可在候选之后试验，避免先建全库图。只有多跳问题在评估集占比上升、关系表难以维护时，才将其中一种图方案升为默认。

### 3.10 LLM Wiki 与 Spec：P1 候选，首期暂不实现 M6

[LLM Wiki 原始说明](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 描述了原始来源、模型维护的 Markdown wiki、schema、ingest/query/lint 和日志；它是模式说明，不是标准化产品。本文采用来源层、整理层和规则层分离的组织方式。“来源不可变”指保留版本而不静默覆盖，不能阻止授权删除或隐私撤回。

M6 的专门 FAQ／主题页／Spec 编辑、审核、派生内容和依赖管理整体列 P1；首期不实现。P0 可以导入已有 FAQ 和流程文本，保留片段、结构化字段及来源定位；这不等于建设页面子系统。后续候选方案为 Markdown 用于审阅和导出，PostgreSQL 保存权限、状态和版本，模型辅助草稿按需引入。Spec 至少有 `purpose`、`preconditions`、`required_slots`、`steps`、`result_branches`、`stop_or_handoff_risks`、`source_refs`、`version` 和 `review_status` 字段，可用 [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) 做结构校验；Schema 校验不等于维修安全批准。

**替代及取舍。** 纯提示词缺少可校验字段，通用工作流引擎又会把少量排查步骤变成额外平台；Pydantic/JSON Schema 适合先约束数据结构，由普通应用逻辑解释有限的步骤／分支。Obsidian 可以作 Markdown 编辑器，但公开服务的权限、版本和审核仍需要后端。Spec 的业务范围由已审核的前提和停止条件决定，不允许模型输出任意代码供服务执行。

价格、配置和安全步骤的模型草稿保留缺失字段、证据和生成时间，经审核才发布；来源撤回时暂停依赖页面。资料中的指令文本只作数据，不得修改应用权限或发布状态。持续提出、评估、审核、发布和回滚的闭环仍是 P2。

### 3.11 知识库对外接口：DRF 契约与结构化证据

**选择及理由。** M7 收敛为知识库对外接口，与 M1 共用 DRF 服务。输入包含原始或已整理文本 `query`、可选的 `preprocess=auto/bypass`、场景 `scenario`、已确认条件 `confirmed_context`、`filters` 与 `top_k`；调用身份由服务端认证映射。输出包含 UUID query_id、index_profile_hash／query_profile_hash、feedback_available、预处理摘要、证据列表、缺失条件、已标注冲突／过期／不足状态。结果使用 contexts[]；每项含父段 ID、完整正文、命中子块 ID 与引用、来源与构建、原文位置、日期、适用条件和已有警告，top_k 计父段数。接口不信任客户端自行声明的角色。

**Schema 与对接。** DRF Serializer 统一请求／响应校验并生成 OpenAPI，示例和客户端测试复用同一契约。字段类型、缺失条件及错误响应见[技术设计第 6 节](./phase1/phase1-technical-design.md#6-对外-api-契约)，本文只记录技术取舍。

引用查看按证据 ID 再次校验访问范围。迭代一至三只返回查询标识和 `feedback_available=false`、记录必要日志；迭代四保存最小 QueryRecord 后返回 true，并开放属于当前调用者且仍在保存期限内的查询反馈。记录写入失败仍返回已完成的检索结果并标记 feedback_available=false，记录故障；无有效记录时反馈接口拒绝请求。维护 API 提供来源提交、元数据修订、导入状态、异常复核、停用和撤回，与管理命令和可选 Admin 共用业务规则；正常导入由服务端自动校验放行。API 测试客户端即可完成首期验收，无需建设聊天入口。

**查询预处理取舍。** 首期通过轻量 prepare_query 接口注入透传处理器，支持 auto／bypass；后续规则或 LLM 处理器复用接口。这样可独立测试、失败回退，也允许外部 Agent 先整理查询，无需引入通用插件系统或新的编排框架。显式条件优先、候选条件与硬过滤分离，模型选择和效果验收见[技术设计第 2.4 节](./phase1/phase1-technical-design.md#24-查询预处理扩展点)。

已有调研中的 [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)、[vLLM](https://github.com/vllm-project/vllm) 和 [Ollama](https://github.com/ollama/ollama) 仅作外部生成服务参考，未做本地测试，不列入知识库首期选型或部署依赖。后续模型辅助知识整理另随 P1/P2 需求评估。

### 3.12 维护入口与 API：Django 5.2 LTS + DRF，Admin 可选

**选择及理由。** [Django 5.2 LTS](https://docs.djangoproject.com/en/5.2/releases/5.2/) 与 [Django REST Framework](https://www.django-rest-framework.org/) 提供模型、迁移、用户、权限、管理命令和 API 组件，适合由少量 Python 维护者运营的模块化单体。首期通过命令／DRF API 完成导入、状态查看、异常复核、发布、撤回及反馈；无需自定义网页后台，也不另引入 CLI 框架。后续非技术成员需要时再增加 Admin 表单。M1 提供入口，M7 定义同一服务的接口契约。批量导入和文档 embedding 由 Worker 执行，评估离线运行；在线编码及可选重排计入 API 耗时。

**维护与发布边界。** 采用自动校验、异常复核和抽查：已获准来源在已验证处理配置下正常导入可自动发布；新类型／解析规则先验收代表样本，硬错误与待复核项不能自动上线。命令、API、Worker 与可选 Admin 共用 M2 发布服务；DBeaver／pgAdmin 仅以只读账号排查，Markdown／HTML 报告可用于父子预览，不直接修改发布指针或在线正文。自动／人工结论记入任务及审计，不新建审批系统。

**替代方案。** FastAPI 也能提供 API 与管理脚本，无网页后台时无需 React；但要另行组合 ORM、迁移和认证。当前选择 Django 的理由是这些基础能力和既定 DRF 契约可复用，不再以“必须有 Admin”为前提。若以后拆分服务，保留证据协议和 PostgreSQL 权威层。

### 3.13 异步任务与最小部署

**首期部署。** 用 Docker Compose 管理 Web/API、单个导入 Worker 和 PostgreSQL；另接可用的 embedding／可选 reranker 推理服务，自托管时再计部署资源。附件按需使用私有文件卷，使用时定期备份。Worker 通过数据库事务领取待处理任务，记录状态、尝试次数、错误、content_hash 与 index_profile_hash；[PostgreSQL 的行锁机制](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE) 可支持这类领取操作，不在模型推理期间持有长事务。

**恢复要求。** Worker 重启后可识别未完成任务，允许有限重试或人工重试；同一任务重试使用固定输入且不重复发布。新构建完成索引并通过自动／人工放行后检查 base_build_id，再切换 current_build_id，失败时继续使用当前构建。更新和索引重建重新取得输入并校验，新处理配置先验收样本，替换后的旧引用返回 404，旧产物可清理；首期不提供历史正文查询或回滚。来源撤回／权限变更先在权威层阻断，再处理片段、索引和已有缓存；M6 上线后再处理派生页面依赖。数据库、配置与实际使用的附件备份和恢复演练均为 P0。

**替代及切换条件。** [Celery](https://docs.celeryq.dev/en/latest/getting-started/introduction.html) 支持多个 Worker、重试和调度，适合并行导入或定时同步增长后接入；Redis/RabbitMQ 等 broker 增加常驻服务，暂列 P1。首期任务表只处理单 Worker 导入，一旦需要复杂调度优先换成熟队列，不自行扩展通用框架。多机共享附件时再接 S3 兼容存储。Kubernetes、Airflow、Kafka 尚无已知需求支撑。

### 3.14 评估与观测：离线检索指标 + 人工集 + 结构化 Trace

**选择及理由。** P0 以人工标注的预期证据和离线脚本计算前 5 命中率、Recall@5/MRR，并检查证据相关性、来源定位、条件／状态、风险信息和权限。记录结构化 Trace：请求 ID、当前构建 ID、候选 ID、融合／重排分数、检索模型与配置版本、耗时、必要用量和错误，默认不保存完整对话或维修原文。

**替代及取舍。** [Ragas](https://github.com/vibrantlabsai/ragas/tree/298b68274234c060deacab3cf5fb52aa3a20e885) 可按需复用检索指标，依赖生成模型的上下文／回答评估留待外部 Agent 集成或后续能力建设。首期不为 LLM judge 增加生成模型接入。无关联 ID 的普通日志难以定位问题；完整观测平台增加部署和敏感数据副本，P1 有排查需求时再接 [Langfuse](https://github.com/langfuse/langfuse)。已有观测系统时可用 OpenTelemetry 贯通链路。

每次比较使用同一批独立保存的评估输入，固定解析器、分块、embedding／reranker、top-k 和证据长度预算；报告检索质量、证据追溯、过期状态、配置串线、风险信息保留、P95 和成本。外部 Agent 的回答可接受率、回答引用支持率及生成延迟另行评估，不作为首期验收前提。

实现正确性与模型质量分开验证：使用 pytest 做规则和编排单测，共享契约测试验证适配器和 API 示例；pytest-django 用于隔离 PostgreSQL 上的事务、唯一约束、过滤与持久化集成测试。单测不调用真实外部服务，不用假向量证明真实召回效果；覆盖率用于发现遗漏，不设任意 100% 指标。具体写法、fixture、mock 和合并要求统一遵守项目单元测试规范。

### 3.15 受控自进化：候选变更 + 离线评估 + 人工发布（P2）

**选择及理由。** 复用已有任务和评估模块；届时按需设计历史保留及回滚能力，再增加候选变更记录：问题来源、原版本、拟修改字段／页面／检索配置、支持证据、评估结果和审核决定。先根据获准反馈与无结果记录整理知识缺口，再生成草稿或别名／检索词候选；开发集用于调整，独立验收集用于决定是否发布。首个试验只选一个高频问题，记录审核时间和模型费用。

**替代及取舍。** 自动把对话写进正式知识库会混入未证实诊断与模型自身输出；自动微调不能快速撤回某条来源；无边界的多 Agent 探索会增加费用与验证负担。因此先用明确输入、输出和审批节点的 Pipeline，不引入自主研究／训练框架。P1 的来源同步、辅助草稿可以独立上线，不以建成此闭环为前提。

候选通过证据检查和离线回归后，由维护者审核发布；不得修改自身评估标准、权限或维修边界。回滚恢复的是上一有效知识／配置版本，当前撤回和权限限制继续生效。没有可重复的收益时停止试验，维持人工维护。

## 4. 论文调研与对选型的影响

### 4.1 2026 年近期工作：优先看与本项目有关的证据

以下数字均为论文作者报告，未在本项目复现。日期按 arXiv 元数据；本节以公开预印本／技术报告作为研究证据，不据此声称均已通过同行评审。

| 论文与日期 | 实际研究内容／结果 | 对模块的影响 | 不能直接外推的地方 |
| --- | --- | --- | --- |
| [Utilizing Metadata for Better Retrieval-Augmented Generation](https://arxiv.org/abs/2601.11863)，2026-01-17 | 25 份 SEC 10-K、4490 个检索单元、120 条测试问题；研究元数据前缀及统一编码，减少同类文档混淆 | 3.4/3.6/3.8：型号、年份、系统既做字段，也可加入检索表示 | 单一财报领域、模板化问题和半合成相关性标注；不是对所有元数据加前缀的普遍保证 |
| [Structure-Aware Chunking for Tabular Data in RAG](https://arxiv.org/html/2605.00318)，2026-05-01 | MAUD 法律数据 39231 行；作者报告混合检索 MRR 从 0.3576 到 0.5945，BM25 Recall@1 从 0.366 到 0.754 | 3.5：配置表按行／键值保留，型号与列头随行传递 | 受控检索实验、启发式相关性定义；未证明端到端生成同幅度提升，BM25 结果也不能直接套给 PGroonga |
| [PAGE-RAG](https://arxiv.org/html/2608.29753)，2026-08-30 | 在候选内建查询局部图；相同最终上下文单元预算下，三个多跳基准加权支持 F1 +10.4、答案 F1 +3.3 个百分点 | 3.8/3.9：将“相关连接”与“能支持断言”区分，必要时试验候选证据选择 | 最终上下文预算相同不等于总计算量相同；找不回从未召回的事实，也未证明维修诊断安全 |
| [MOSAIC](https://arxiv.org/html/2609.11065)，2026-09-10 技术报告 | query 分析器配置有边界的图探索；同图／生成器 Medical 对照中，准确性 76.97 对固定中等策略 67.01，图遍历减少但端到端延迟增加 | 3.15：P2 可研究按问题类型调整检索宽度和预算 | 实现含专有组件，开放受控；部分外部基线采用已发表数字。仅借鉴策略思路，不推荐为可直接部署的开源组件 |

本轮也检索到 [ESG 报告 RAG 评估（09-14）](https://arxiv.org/abs/2609.15242)、[Semantics Delivery Network（09-18）](https://arxiv.org/abs/2609.22486) 和 [EHR living benchmark（09-24）](https://arxiv.org/abs/2609.30205)。前者的合成问题与模型评估设置不足以替本项目选生成模型；后两者侧重 Web 检索基础设施／医疗基准，未纳入核心选型依据。最新日期不是选择标准，本次检索也不是穷尽全部 RAG 文献的系统综述。

### 4.2 基础与组件相关工作

| 论文 | 公开版本时间 | 与选型的关系 | 采用边界 |
| --- | --- | --- | --- |
| [Ragas: Automated Evaluation of RAG](https://arxiv.org/abs/2309.15217) | 2023-09 | 分开检查检索相关性、上下文利用和生成质量 | 自动评估辅助人工，不将 judge 分数当绝对事实 |
| [BGE-M3](https://arxiv.org/abs/2402.03216) | 2024-02 | 同一模型支持 dense、sparse、多向量表示 | 首期只比较 dense；其他模式各自增加索引和检索成本 |
| [From Local to Global: A Graph RAG Approach](https://arxiv.org/abs/2404.16130) | 2024-04 | 社区摘要面向跨文档全局问题 | 主题归纳有需求时再评估；项目维护状态另据官方仓库判断 |
| [Late Chunking](https://arxiv.org/abs/2409.04701) | 2024-09 | 长文编码后分块池化以保留语境 | 需兼容模型；不直接套到当前 Qwen 池化方式 |
| [LightRAG](https://arxiv.org/abs/2410.05779) | 2024-10；v3 2025-04 | 图／向量与双层检索，考虑增量更新 | P1 关联查询的对照候选，当前产品能力还需看仓库 |
| [Qwen3 Embedding](https://arxiv.org/abs/2506.05176) | 2025-06 | 0.6B/4B/8B embedding 与 reranker，多语言和指令接口 | 选择 0.6B 作起点；不能把 8B 的历史榜单成绩当成 0.6B 当前成绩 |
| [T²-RAGBench](https://arxiv.org/abs/2506.12071) | 2025 初版；v2 2026-01 | 文本和表格混合检索／问答需要专项评估 | 电脑配置表进入本地问题集，不直接照搬其基准分数 |

工程采用顺序因此为：先验证结构、元数据和证据引用，再依据多跳失败样本评估图增强，最后在 P2 研究策略自适应。论文用于提出可验证假设，最终选择由本地数据和维护成本决定。

## 5. 首期实施边界与验收顺序

### 5.1 P0 必做

1. 三类授权文本人工导入；来源与构建、脱敏、公开／内部范围和撤回状态。
2. PostgreSQL + pgvector + PGroonga；类型化分块和机型／配置等必要字段。
3. Qwen3 embedding 初始方案及 BGE-M3 dense 对照；混合召回、RRF、可开关重排、引用证据包。
4. 维护来源片段、配置、案例和必要关联；保留购机资料日期、适用条件及维修警告，不建设 M6 页面子系统。
5. Django 管理命令与 DRF 知识查询／维护 API，Django Admin 可选；Python 模块化导入流程、PostgreSQL 任务表与单 Worker，正常任务自动发布、异常人工复核。
6. 代表性问题集、离线评估、基础 Trace、权限审计和数据库／文件备份恢复；迭代四补齐持久化查询记录与反馈。
7. 索引／查询配置分层、适配器协议、可生成的 API Schema，以及项目单元／契约测试规范。

Reranker 是 P0 的可验证候选和关闭配置，而非未经测试的强制推理服务；复杂 PDF／OCR 由 P1 的实际样本触发，原生文本解析属于 P0。

P0 按技术设计第 8 节分为四个独立可运行迭代：关键词维护查询、文件导入与词法检索、混合召回、反馈与试用发布。早期版本不依赖后续模型或查询记录表；每个阶段须交付空库启动和升级验收，不能把未实现功能返回成功占位状态。

### 5.2 P1 增强

- 非技术维护者需要表单操作时启用 Django Admin；复用既有业务服务，不重写一套审核和发布逻辑。
- 查询预处理：通过首期已保留的接口接入意图规则、查询改写或 LLM 结构化提取；以固定问题集验证收益、条件保留、bypass 和失败回退，不要求同时建设 Agent 或 M6。
- 获准来源的增量同步、复杂文档解析／OCR；P0 已包含来源更新后的片段与索引处理。
- F-17 / M6：FAQ／主题页／Spec 编辑、审核及派生内容依赖管理；首期暂不实现。
- F-19 模型辅助草稿、F-16 科普素材整理，按明确需求建设。
- Haystack 等编排框架在模块组合与复用成本上升时再引入。
- F-11 关联查询；SQL 不足时试验 LightRAG 或查询局部证据图。
- 因实际并发、共享存储或排查需要增加 Celery、S3 兼容存储、Langfuse；均按需引入。

### 5.3 P2 探索

- F-21～F-24：从缺口发现到候选生成、回归、人审、发布、回滚的持续闭环。
- F-25：查询类型驱动的召回宽度、深度、分块、提示或 Spec 优化。
- 有足够的高质量、脱敏、审核样本且收益明确后，再评估微调或蒸馏。

### 5.4 模块与需求对应

| 技术模块 | 主要功能需求 | 主要非功能需求 |
| --- | --- | --- |
| 3.1～3.3 接入、发布、存储 | F-01～F-06 | N-02、N-03、N-04、N-06 |
| 3.4～3.8 分块、检索与证据 | F-02、F-04、F-07～F-10 | N-01、N-02、N-04、N-10 |
| 3.9 关系与图增强 | F-04（P0）、F-11（P1） | N-01、N-02、N-08 |
| 3.10 Wiki／Spec（P1） | F-16、F-17、F-19 | N-01、N-02、N-03、N-05 |
| 3.11 知识库对外接口（P0） | F-08～F-10、F-12～F-15、F-18 | N-01、N-02、N-04、N-07 |
| 3.12～3.13 管理与运行 | F-01、F-03、F-05、F-18（P0）；F-06、F-17（P1） | N-04、N-06、N-07、N-08 |
| 3.14 评估观测 | F-18、F-20 | N-01、N-09、N-10 |
| 3.15 自进化（P2） | F-21～F-25 | N-01～N-06、N-09、N-10 |

## 6. 技术风险与验证计划

### 6.1 小规模 PoC：用同一问题集决定技术，而非一次比较所有组合

先从语雀、维修文本和推荐文章各抽 10–20 份授权样本，包含配置表、不同年份、缺失信息和来源冲突。按需求文档准备至少 60 个问题，常识、购机、维修各不少于 15 个；尽量来自真实脱敏咨询，由成员标注有效依据、必要条件和可接受结果。预留一部分独立验收题，调参时不看其答案。60 题仅能支持初步决策，应同时给出命中数量／总数，不能用小样本声称普遍领先。

| 步骤 | 比较方式 | 需要回答的问题／选择规则 |
| --- | --- | --- |
| 1. 数据可用性 | 检查标题、表格行、警告、型号／年份、证据定位；普通文本先原生解析，复杂样本再加 Docling | 解析残缺则先补录或换解析器；不靠换向量模型掩盖来源缺失 |
| 2. 最小检索基线 | 在相同分块和过滤下，比较词法、Qwen dense、RRF 混合；再单独将 dense 换成 BGE-M3 | 记录前 5 命中、MRR、型号精确匹配和无答案处理；保持所有方案相同权限条件 |
| 3. 定向消融 | 在较好基线上逐项比较结构分块／递归分块、元数据前缀有无、reranker 开关 | 一次改变一个因素；有足够质量收益且成本可接受才保留复杂项 |
| 4. 接口与证据验收 | 用 API 测试客户端运行 A-01～A-14 及独立题集，检查证据 ID、当前构建、权限、条件／状态和引用查看 | 检查购机适用性、维修风险信息及证据完整性，不依赖回答生成 |
| 5. 运行与恢复 | 试测 1000 篇文本、5 并发，另报总文本量／chunk 数；验证重复导入、撤回、权限变更和备份恢复 | 记录 CPU/GPU、内存、量化、批大小、数据库／模型版本及 P50/P95；瓶颈在哪个阶段，再升级哪个组件 |

第一轮只运行无 reranker／0.6B reranker 和两个 dense 候选，不展开所有模型与平台的排列组合。如果维护人力不足，直接用同一组样本试用 MaxKB 或 RAGFlow，把维护者完成导入、纠错、撤回所需的时间一并比较。

### 6.2 验收口径与未验证事项

沿用需求文档的**首期建议目标**：前 5 条至少一项有效证据的命中率 ≥90%，证据追溯、时效、配置和权限等专项用例全部通过；检索 P95 ≤2 秒。外部 Agent 集成后的回答可接受率 ≥85%、回答引用支持率 ≥95% 和完整回答 P95 ≤20 秒另行验证，不属于知识库首期门槛。以上均未实测，需先确认硬件与模型预算。命中率不同于“所有相关证据的 Recall@5”；多证据问题应另查全部关键依据，不能以命中一段替代完整性。

性能报告把查询预处理、query embedding、数据库召回、重排和排队分别计时；检索响应口径包含在线预处理、embedding 与重排，不仅是 SQL 时间。还需记录每次导入／查询的处理用量、推理耗时、外部费用及社员审核时间。Agent 侧改写的耗时和费用计入外部应用端到端指标；在知识库内启用的查询处理器则计入知识库 API 的 P95 和查询成本，并记录处理器版本和回退状态。

此次完成的是资料调研与文档选型：未取得真实语料，未安装平台／数据库扩展，未运行 GPU 推理、负载测试或论文复现。授权范围、实际格式、维护人力、服务器和预算需在 PoC 前确认；未确认时保持人工文本导入和最小部署假设。

### 6.3 主要风险与处理

| 风险 | 影响 | 验证与缓解 |
| --- | --- | --- |
| PGroonga 与目标 PostgreSQL 环境不兼容 | 词法召回方案无法部署 | 先核对同版本扩展镜像；不满足时试预分词 + 原生 FTS，仍不足再评估 OpenSearch |
| embedding／reranker 不适配或过慢 | 召回差或超出对话延迟 | 按 6.1 对照 Qwen／BGE，分别测召回与重排；云端基线仅在获准时使用 |
| 配置和价格串线 | 购机建议错误 | 结构化字段过滤 + 引用校验 + 不同年份/配置对抗用例 |
| 维修案例被误当作通用结论 | 用户采取不安全操作 | 案例/推测/已确认状态分离；高风险步骤强制人工审核和转交 |
| HNSW 过滤后候选不足 | 漏召回 | 与带相同条件的精确检索对比，按需调整 iterative scans 和候选量 |
| 权限／撤回检查遗漏 | 内部知识泄露或错误知识继续使用 | SQL 授权条件、候选和引用复核、依赖失效；A-10／A-12 专项验证 |
| 解析器遗漏图片/表格 | 关键配置和警告缺失 | 保存解析告警、人工抽样、难例 fallback；不能将空解析结果发布 |
| 外部模型或第三方来源权限不清 | 合规/隐私风险 | 原始资料授权字段、外部调用白名单、脱敏前置、删除和撤回传播测试 |
| 自动评估偏差 | 错误更新被误采纳 | held-out 问题集、人工安全评审、固定模型/提示/预算记录 |
| 自建工作超过维护能力 | 无法持续更新 | 评估开发与交接时间，必要时选择 MaxKB／RAGFlow；备份、升级、恢复文档随 P0 交付 |

## 7. 参考资料

### 7.1 官方开源项目与组件

- [RAGFlow README（Apache-2.0，提交快照）](https://github.com/infiniflow/ragflow/tree/313ca90f6abd7682fe8523e16fd67b3653a3fa84)
- [Dify README](https://github.com/langgenius/dify/tree/725611b2e9a425519e9fcb4dcc579bafea936d27) 与 [许可证](https://github.com/langgenius/dify/blob/725611b2e9a425519e9fcb4dcc579bafea936d27/LICENSE)
- [FastGPT README](https://github.com/labring/FastGPT/tree/b3ec46218d08a7b3e4c72e0eea7a9baebca2f736) 与 [检索实现](https://github.com/labring/FastGPT/tree/b3ec46218d08a7b3e4c72e0eea7a9baebca2f736/packages/service/core/dataset/search/defaultRecall)
- [MaxKB README（Django + PostgreSQL + pgvector，GPLv3）](https://github.com/1Panel-dev/MaxKB/tree/bfbbffb859bf7bbebf5f83b6f4adb1de8dbfaba1)
- [Onyx README](https://github.com/onyx-dot-app/onyx/tree/65912e1bf4bcc56ac5d04fb776fc262c58f4b55d)
- [Haystack README](https://github.com/deepset-ai/haystack/tree/8a5406eea71a0fc19e94c4b9a5cd96df2158a45a) 与 [DocumentJoiner](https://github.com/deepset-ai/haystack/blob/8a5406eea71a0fc19e94c4b9a5cd96df2158a45a/haystack/components/joiners/document_joiner.py)
- [LlamaIndex README](https://github.com/run-llama/llama_index/tree/169e450aa54d26ed3e0536b1a0f1ea537871aa5d)
- [LightRAG README](https://github.com/HKUDS/LightRAG/tree/453dce83d6d0354a06e46c8d4029a0895c4e054b)
- [Microsoft GraphRAG README](https://github.com/microsoft/graphrag/tree/769542fbf1d8e5b4c6a8677fefc34621c87894c5)
- [Docling README](https://github.com/docling-project/docling/tree/2d5c590c34b6378fd8a47c65b534b280aa40c93c)
- [pgvector README](https://github.com/pgvector/pgvector/tree/7db2345ed99bc77bf33cbdc8b12bd1973210dc81)
- [Qdrant README](https://github.com/qdrant/qdrant/tree/6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de)
- [PGroonga 官方说明](https://pgroonga.github.io/)
- [Qwen3-Embedding-0.6B 模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Qwen3-Reranker-0.6B 模型卡](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)
- [Qwen3.5-9B 模型卡](https://huggingface.co/Qwen/Qwen3.5-9B)
- [BGE-M3 模型卡](https://huggingface.co/BAAI/bge-m3)
- [Ragas README](https://github.com/vibrantlabsai/ragas/tree/298b68274234c060deacab3cf5fb52aa3a20e885)
- [Karpathy LLM Wiki 原始说明](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [Docling 分块文档](https://docling-project.github.io/docling/concepts/chunking/)、[Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [Django 5.2 LTS](https://docs.djangoproject.com/en/5.2/releases/5.2/)、[DRF](https://www.django-rest-framework.org/)、[Celery](https://docs.celeryq.dev/en/latest/getting-started/introduction.html)

### 7.2 论文

- [Ragas，arXiv:2309.15217](https://arxiv.org/abs/2309.15217)
- [BGE-M3，arXiv:2402.03216](https://arxiv.org/abs/2402.03216)
- [From Local to Global: A Graph RAG Approach，arXiv:2404.16130](https://arxiv.org/abs/2404.16130)
- [Late Chunking，arXiv:2409.04701](https://arxiv.org/abs/2409.04701)
- [LightRAG，arXiv:2410.05779](https://arxiv.org/abs/2410.05779)
- [Qwen3 Embedding，arXiv:2506.05176](https://arxiv.org/abs/2506.05176)
- [T²-RAGBench，arXiv:2506.12071](https://arxiv.org/abs/2506.12071)
- [Utilizing Metadata for Better RAG，arXiv:2601.11863](https://arxiv.org/abs/2601.11863)
- [Structure-Aware Chunking for Tabular Data，arXiv:2605.00318](https://arxiv.org/abs/2605.00318)
- [PAGE-RAG，arXiv:2608.29753](https://arxiv.org/abs/2608.29753)
- [MOSAIC，arXiv:2609.11065](https://arxiv.org/abs/2609.11065)

### 7.3 搜索与证据方法摘要

工具为 OpenCLI 的 Google／arXiv 搜索与公开网页读取；GitHub、模型卡、官方组件文档和 arXiv 原文用于核验。未调用外部 AI。按用户要求，不因默认搜索次数限制停止必要研究。

| 搜索网站 | 实际查询词 | 次数与结果 |
| --- | --- | --- |
| Google | `open source RAG knowledge base RAGFlow Dify FastGPT Onyx architecture hybrid retrieval` | 1 次成功 |
| Google | `site:arxiv.org retrieval augmented generation knowledge retrieval September August July 2026 benchmark` | 1 次成功 |
| Google | `site:arxiv.org 2026 "knowledge" "RAG" "September" graph retrieval` | 1 次成功 |
| Google | `site:github.com Qwen3.5 9B embedding Qwen3 0.6B model` | 1 次成功 |
| Google | `LLM Wiki Karpathy gist github raw wiki compiled knowledge` | 1 次成功 |
| arXiv | `retrieval augmented generation knowledge base` | 2 次：1 次 DNS 失败、1 次成功 |
| arXiv | `graph retrieval augmented generation` | 1 次 DNS 失败 |
| arXiv | `agentic retrieval knowledge base` | 1 次 DNS 失败 |
| arXiv | `GraphRAG LightRAG retrieval augmented generation` | 1 次成功 |
| arXiv | `retrieval augmented generation evaluation citation faithfulness` | 1 次成功 |
| arXiv | `structure aware chunking retrieval augmented generation` | 1 次成功 |
| arXiv | `agentic retrieval augmented generation adaptive retrieval` | 1 次成功 |

合计 Google 5 次成功，arXiv 8 次尝试（5 成功、3 失败）；失败查询不作为证据。arXiv 关键词结果较宽，补用 Google 定位后回到官方原文核对。浏览器并行读取曾被导航冲突拒绝，随后改用顺序读取或公共 HTTP 读取；预检、帮助和直接读取不计入上述搜索次数，无因限频跳过的站点。

覆盖五个完整平台、两个可组合框架、两个图增强项目，以及解析、数据库、模型和评估组件。未做全市场排名或生产性能测试。源码链接固定到已读提交；未固定的组件文档／模型卡记录的是本次访问时的内容，实施时仍须锁定依赖版本和权重 revision。

## 8. 最终建议

按当前“至少一名 Python 维护者、资料格式尚未完全确认、先按 1000 篇／5 并发试测”的假设，先建设以 PostgreSQL 为来源和权限中心的轻量知识服务：Django 提供认证与管理命令，DRF 提供知识查询与维护 API，Admin 按需启用；Python 模块化流程、任务表和单 Worker 执行导入，正常任务自动校验发布、异常人工复核；查询预处理首期透传，PGroonga + pgvector + RRF 提供混合召回，reranker 通过消融决定是否启用；返回带构建标识和出处的当前证据。智能查询预处理、M6 知识页／Spec、模型草稿和图增强列 P1，Haystack 为后续可选框架，持续自进化列 P2。Agent 开发及最终回答生成属于外部应用；知识库可按需接入用于查询理解的模型。

这条路径的代价是要自己实现质量检查、异常复核命令／API、证据协议、备份和少量任务处理，网页界面按需增加。如果维护者时间不足，先用同一验收集试用 MaxKB 或 RAGFlow；如果其导入、纠错、撤回、权限和引用效果满足需求，可以选择平台方案，技术选型随验证结果调整。

实现前先从三类来源各抽样 10–20 份资料，完成解析、分块、召回、引用、权限和恢复的端到端 PoC，并按第 6 节记录硬件、chunk 数、模型版本、P95 和审核时间；这些实测结果再决定是否引入独立向量库、Celery、Langfuse、图检索或自进化闭环。
