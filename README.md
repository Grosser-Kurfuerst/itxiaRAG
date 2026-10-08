# itxiaAgent 知识库

当前仓库实现的是一个可运行的最小混合检索知识库：调用方提交标准化文档，或提交 HTML/Markdown/文本经可编排预处理后导入，系统保存父段和子块，使用关键词与向量两路召回，经 RRF 排序后返回完整父上下文。文章抓取和最终回答由后续模块负责，当前没有 Agent 或审核发布流程。

合成标准化请求见 [fixtures/iteration1/basic.json](fixtures/iteration1/basic.json)，原文请求见[文档预处理](docs/phase1/preprocessing.md#6-原文导入-api)。

## 文档导航

| 文档 | 负责维护的内容 |
| --- | --- |
| [总体需求](docs/requirements.md) | 业务场景、当前范围、P1 扩展与 P2 自进化 |
| [技术选型与研究参考](docs/technology-selection.md) | 当前选择理由、替代方案、开源与论文依据 |
| [首期技术设计](docs/phase1/phase1-technical-design.md) | 模块、公共 DTO、存储、检索、API 响应与错误、迁移 |
| [来源接入说明](docs/phase1/source-ingestion-plan.md) | 资料获取与准备、提交方式选择、更新与后续平台连接器 |
| [文档预处理](docs/phase1/preprocessing.md) | 原文请求、格式适配器、父子段策略、长度预算与步骤扩展 |
| [Docker 部署与验收](docs/phase1/deployment.md) | Compose 配置、启动、账号、标准／原文导入冒烟检查和日常操作 |
| [项目测试规则](docs/unit-testing-guidelines.md) | 测试环境、预处理专项、回归命令与完成定义 |

建议按任务阅读：

- 了解项目：总体需求 → 技术选型 → 首期技术设计。
- 接入资料：来源接入说明 → 文档预处理 → 专项测试。
- 运行与验收：下方本地运行或 Docker 部署 → 项目测试规则。

每项契约或操作在对应文档维护，其他文档保留概述和链接；实现变化时同步对应文档。外部资料与历史验证记录注明日期和适用范围，不作为当前实现状态或测试结果。

## Docker 运行

推荐按 [Docker 部署与验收](docs/phase1/deployment.md) 启动。Compose 提供 Web、PostgreSQL、可选的 Ollama 模型服务和独立测试镜像；文档包含配置、模型下载、账号创建、导入／检索验收及停止备份步骤。

## 本地运行

需要 Python 3.12、PostgreSQL 和兼容 OpenAI `/embeddings` 协议的模型服务（本地或已获准的外部服务）。安装依赖：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

本地配置放在项目目录的被忽略文件中：

```sh
cp .env.example .env.local
chmod 600 .env.local
# 编辑 .env.local 的密钥、数据库连接和 Embedding 服务参数
set -a; . ./.env.local; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

必须配置 `EMBEDDING_BASE_URL`、模型名、维度和 revision；缺少时导入／检索返回 503，不使用伪向量代替语义模型。更换模型、revision 或 query 指令后须重新导入资料。`.env.example` 的模型名只是配置示例，不会自动部署或下载模型。

账号只通过部署侧创建：

```sh
mkdir -p .runtime
.venv/bin/python manage.py kb_account --username maintainer --permissions maintain_source,read_internal --token-file .runtime/maintainer.token
```

导入接口需要 `maintain_source`：

```sh
curl -H "Authorization: Token $(cat .runtime/maintainer.token)" \
  -H 'Content-Type: application/json' \
  -d @fixtures/iteration1/basic.json \
  http://127.0.0.1:8000/api/v1/sources/
```

返回 `source_id`、`context_ids` 和 `reused`。更新同一来源时保留同 key 段落的 ID；相同内容返回 `reused=true`。Embedding 完成后才开启数据库事务，任意写入失败会回滚。

原文可以提交到 `POST /api/v1/sources/raw/`，选择 `product_review`、`purchase_guide` 或 `experience_case`；请求示例、格式适配、分段策略、预算与扩展方式见[文档预处理](docs/phase1/preprocessing.md)。API 不抓取 URL 或执行 OCR，调用方提供原文。

查询接口：

```sh
curl -H "Authorization: Token $(cat .runtime/maintainer.token)" \
  -H 'Content-Type: application/json' \
  -d '{"query":"电池能用多久","top_k":5}' \
  http://127.0.0.1:8000/api/v1/search/
```

普通账号只获得公开来源；`read_internal` 才能检索内部来源。Embedding 故障返回 502，不静默降级为空结果。

关键词路使用 jieba 分词与 Python BM25，向量路继续编码完整查询；两路通过可编排流水线经 RRF 融合、父段聚合后返回。BM25 每次只读取当前可见子块并计算，内容更新立即生效；没有持久关键词索引或缓存，适合小规模验证。可通过 `RETRIEVAL_MIN_COSINE` 和 `RETRIEVAL_MIN_BM25` 配置独立路线门槛。

## 验证

```sh
make test-unit
make test-integration
make test
```

环境要求、分层运行和预处理专项命令见[项目测试规则](docs/unit-testing-guidelines.md)。测试使用合成资料和测试 Embedding；真实模型的语义质量、吞吐和容量需要单独用获准样本验证。旧开发表收敛和 knowledge_type 字段删除的区别见[迁移说明](docs/phase1/phase1-technical-design.md#7-验收与迁移)。
