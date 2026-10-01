# 首期迭代一：最小混合检索实现

本实现替代原审核／发布版本。规范以 [技术设计](phase1-technical-design.md) 和实际 Serializer 为准。

## 1. 当前范围

提供两个 API：标准化文档同步导入，以及关键词 + 向量 + RRF 查询。存储三张业务表，按输入父子关系保存。**不实现文章获取、解析、清洗、父子分段或查询预处理**。

删除导入任务表、配置单例、审核／自动放行／发布／撤回／审计，删除对应 API、管理命令、profile、健康探针、维护模式、Compose、演示初始化及验收矩阵。保留必要数据库迁移和账号 Token 发放命令；普通事务用于避免部分保存。

## 2. 模块结构与改动点

```text
api/                 sources 与 search 两个入口、有限 JSON 请求体
contracts/           types.py：DTO/Protocol；serializers.py：标准文档校验；query.py
catalog/             models.py：三表；storage.py：DocumentStore；selectors.py：范围和父段读取
embeddings/          openai_compatible.py：真实 HTTP 适配器；validation.py：向量校验
ingestion/           pipeline.py：校验/编码/保存；registry.py：预处理策略注册，无具体插件
retrieval/           keyword.py、vector.py、hybrid.py、service.py
config/              settings.py 配置；components.py 组合根
fixtures/iteration1/ basic.json 合成标准化评测
tests/              unit 与 integration 两类必要测试
```

- `ProcessedDocument` 显式包含父段和子块；key 是稳定业务键，位置由数组顺序决定。来源权限放 `SourceSpec`，不由插件输出。
- `import_processed(source, document, actor, *, embedder, store)` 是统一导入入口。未通过权限与内容校验时不调用模型，模型完成后交给存储事务。
- `DjangoDocumentStore.save(...)` 去重并按段落 key 更新。仍存在的段落 ID 不变；已从新输入删除的段落同步删除。不生成版本或发布候选。
- `EmbeddingProvider` 分文档与查询编码；适配器批量调用 `/embeddings`，验证返回索引、数量、维度、有限值与非零向量。失败不保存半份内容，不返回模拟向量。
- `HybridRetriever` 组合多个 `Retriever` 与 `Ranker`。默认 PostgreSQL 关键词 + PostgreSQL JSONB 向量的 Python 精确余弦检索 + RRF；后续按相同协议切换 pgvector 或重排。
- `DjangoContextReader` 返回完整父段、来源、定位、命中子块 ID 与排名、引用；父段按最佳子块排序。
- `PreprocessorRegistry` 按 `(document_schema, schema_version)` 显式注册，校验输出。当前空注册，不从 API 动态加载代码。

## 3. 输入与响应

完整导入样本见 [basic.json](../../fixtures/iteration1/basic.json)。维护者提交：

```http
POST /api/v1/sources/
Authorization: Token <token>
Content-Type: application/json
```

请求含 `source` 和 `document`。响应示例：

```json
{"source_id":"00000000-0000-0000-0000-000000000001","context_ids":["00000000-0000-0000-0000-000000000002"],"reused":false}
```

同步完成均返回 200，无 pending/failed 任务；失败使用 HTTP 错误，修正后重新提交。去重不免除本轮 Embedding 调用。

查询输入：

```json
{"query":"笔记本 A 电池能用多久","filters":{"knowledge_types":["product_spec"]},"top_k":5}
```

返回 `mode=hybrid`、`result_status=found/no_result`、`contexts[]`。每项含 `context_id/key/title/text/locator/metadata/warnings/source/score/matches/citations`。`matches` 含每个命中子块 ID、RRF 分数与各路名次。`citations` 包括父段内全部子块的定位和 metadata。知识类型只过滤召回，完整父段不按该过滤裁切。

正文保留输入原样；不能同时要求自动拆段。每篇最多 100 父段、每父最多 100 子块、总计最多 1000 子块；请求体上限 2 MiB。父段正文上限 100000 字、子块 32000 字。来源类型、文档 Schema、知识类型允许新增规范化标识，专有字段使用 metadata。

## 4. 可独立验收的实现步骤

| 步骤 | 交付 | 验收 |
| --- | --- | --- |
| 1 | DTO、Serializer、插件注册协议 | `make test-unit`：合法输入保真、结构非法拒绝、注册/替换行为通过；不需数据库或模型 |
| 2 | 三表、事务保存与稳定 key | PostgreSQL 集成：新建、重复、更新、权限与回滚通过；通过受控测试向量运行，不需外部模型 |
| 3 | 关键词、向量、RRF、父段聚合 | 受控向量样本验证同义词仅命中向量路、两路同 Scope、RRF 次序、完整父段与引用 |
| 4 | HTTP 模型适配器、两个 API | 使用真实 Token 调用导入和查询；验证错误码、移除旧路由；本地 HTTP 服务验证模型协议；`make test` 全部通过 |
| 5（后续） | 笔吧等来源的具体插件 | 获准真实样本验证预处理与质量，调用相同导入服务，已有回归通过 |

只有步骤 4 及真实 Embedding 配置同时具备，才可用于实际语义检索。自动化测试的固定向量和 HTTP 模型替身只验证工程行为，不证明模型质量。

## 5. 本地运行与约束

依赖安装、环境变量、账号和两条 API 调用见 [README](../../README.md)。`make migrate` 只初始化数据库，不创建演示数据或系统账号；`make run` 启动 Django。

旧库有业务资料时迁移主动中止，不执行破坏性表变更；新版本使用新数据库，旧资料需要按 DTO 重新整理导入。此轮不实现在线升级或历史数据自动转换。

后续更换模型须改变 revision 并重新导入。仅调整候选数、RRF 或 top_k 不重建。JSONB 精确向量查询需扫描可见子块，实际容量与模型效果尚须实测；扩容点为 VectorRetriever 和存储适配器。
