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
| [来源连接器改造方案](docs/phase1/source-connector-design.md) | 通用连接器协议、清单与导入服务的拆分，平台差异与迁移步骤；未实现 |
| [语雀文档导入方案](docs/phase1/yuque-ingestion/overview.md) | 语雀解析、教程／知识／工具条目流水线、快照导入与 OpenAPI 读取已实现；Token 实测与真实 Embedding 检索抽查待补 |
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

原文可以提交到 `POST /api/v1/sources/raw/`，选择 `product_review`、`purchase_guide`、`experience_case` 或 `tutorial`；请求示例、格式适配、分段策略、预算与扩展方式见[文档预处理](docs/phase1/preprocessing.md)。API 不抓取 URL 或执行 OCR，调用方提供原文。

查询接口：

```sh
curl -H "Authorization: Token $(cat .runtime/maintainer.token)" \
  -H 'Content-Type: application/json' \
  -d '{"query":"电池能用多久","top_k":5}' \
  http://127.0.0.1:8000/api/v1/search/
```

普通账号只获得公开来源；`read_internal` 才能检索内部来源。Embedding 故障返回 502，不静默降级为空结果。

关键词路使用 jieba 分词（含 [领域词典](retrieval/keyword-terms.txt)）与 Python BM25，向量路继续编码完整查询；两路通过可编排流水线经 RRF 融合、父段聚合后返回。BM25 每次只读取当前可见子块并计算，内容更新立即生效；没有持久关键词索引或缓存，适合小规模验证。可通过 `RETRIEVAL_MIN_COSINE` 和 `RETRIEVAL_MIN_BM25` 配置独立路线门槛。

## 语雀导入

阶段 1～3 与阶段 4 的代码已实现，可从官方 OpenAPI 或本机快照批量处理教程、知识与工具条目。需 Token 的接口实测与真实教程验收待 Token 到位后补测；阶段 5、6 代码已实现，第一批 74 篇快照试运行 0 失败，真实 Embedding 检索抽查待补。清单见 [itxia.toml](sources/yuque/manifests/itxia.toml)，快照格式见[技术方案 7.1](docs/phase1/yuque-ingestion/technical-design.md#71-平台读取)，快照与原文放在被忽略的 `.runtime/` 下。

OpenAPI 模式从环境变量 `YUQUE_TOKEN` 读取获授权的语雀 Token，空值会启动失败；`YUQUE_API_BASE` 默认 `https://www.yuque.com/api/v2`，空值也使用默认地址。实际 Token 只填入被忽略的本地环境文件并加载，不作为命令参数，也不写入报告或快照。离线模式无需这两项配置。

```sh
# OpenAPI 试运行并保存快照：需先加载含 YUQUE_TOKEN 的本地配置
.venv/bin/python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
  --save-snapshot .runtime/yuque-openapi-snapshot --dry-run

# 离线试运行：无需账号、Embedding 或数据库连接，只预处理、不保存
.venv/bin/python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
  --snapshot .runtime/yuque-snapshot --dry-run

# OpenAPI 正式导入：可重复 --only；去掉 --only 时处理清单中所有知识库
.venv/bin/python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
  --username maintainer --only help/install_win10
```

`--snapshot` 与 `--save-snapshot` 互斥。保存快照时先读取清单内所有知识库的已分类文档正文（含未接入的排障和案例），再从快照执行导入；`--only` 只限制导入范围，不缩小保存范围。目录与完整分页列表也会保存，跳过和未登记的文档不保存正文。该范围覆盖清单中的第一批 74 篇，实际完整性仍需用真实目录和读取报告核对。保存时任一单篇读取失败均记为 `failed`，即使该类别未接入或不在 `--only` 中；失败正文不保留旧文件，快照可能不完整，应重跑补齐。

仍需加载本地 Django 配置。正式导入需要 `maintain_source`，内部来源另需 `read_internal`；当前清单全部为 public，internal 保留备用。试运行若提供 `--username` 也会检查账号权限。报告区分 `preprocessed`（试运行成功）、`imported`、`reused`、`skipped`、`unregistered`、`failed`，列出父段／子块数与警告，不打印正文。排障和案例类别未接入，报告为“未接入”；清单错误或正式导入缺少 Embedding 配置会启动即失败；单篇失败继续处理，批次结束以非零状态退出。重复运行按现有主链更新或返回 `reused`。

OpenAPI 的 401／403 会终止整批并提示检查 Token 与知识库权限；详情读取的 429、其他 HTTP／网络错误、超时和格式错误记为单篇失败。目录或文档列表读取失败时整批终止，尚不处理任何正文。容器内配置和操作见[部署与验收](docs/phase1/deployment.md#37-语雀-openapi-与快照导入)。

## 公众号采集导入

第三方公众号不能在线批量读取，笔吧推文采用“下载或人工采集 + 离线导入”。清单 [bibar.toml](sources/wechat/manifests/bibar.toml) 的 `[connector]` 登记账号名与文章标题、发布日期，`fetch_wechat` 经搜狗微信搜索逐篇下载；账号、标题（统一全角半角）与日期全部一致才算找到，找不到或多篇一致记为单篇失败，不猜测，继续下一篇，结束后以非零状态退出。已下载的文章跳过（`--force` 重下），`--only` 可重复、只下载指定条目，默认每次请求间隔 3 秒（`--interval`），出现验证码时整批终止，稍后重跑即可续传。`import_wechat` 同样校验 `[connector]`，写错时启动即失败，不会被静默忽略。下载结果只有 `__biz/mid/idx` 链接，缺少 `sn`，原文链接打不开但身份稳定；每期同名的文章（如选购指南）搜狗通常搜不到最新一期，需人工采集。

```sh
.venv/bin/python manage.py fetch_wechat --manifest sources/wechat/manifests/bibar.toml \
  --capture .runtime/wechat-capture
```

人工采集时把获准文章网页保存为 `<目录>/<账号目录>/<条目>.html`，同名 `.json` 旁注写 `title`（必填）、`url`、`date`、`author`、`account`。`url` 须是永久链接（含 `__biz`、`mid`、`idx`）或短链接，临时链接会报错；没有链接时以采集文件名作身份，入库后不要再改名或更换链接形式；采集目录含原文，放在被忽略的 `.runtime/` 下，不提交；清单只含标题、日期与分类。清单格式与身份规则见[来源连接器改造方案](docs/phase1/source-connector-design.md#5-清单)，评测须逐篇在 `metadata` 中登记 `entity_title`。

```sh
# 试运行：无需账号、Embedding 或数据库连接
.venv/bin/python manage.py import_wechat --manifest sources/wechat/manifests/bibar.toml \
  --capture .runtime/wechat-capture --dry-run

# 正式导入：账号需 maintain_source，internal 来源另需 read_internal
.venv/bin/python manage.py import_wechat --manifest sources/wechat/manifests/bibar.toml \
  --capture .runtime/wechat-capture --username maintainer
```

`--only`、`--dry-run`、`--username` 与报告状态同语雀导入。旁注缺失或非法、账号目录不存在、同一文章重复采集时整批终止；单篇读取或预处理失败记为 `failed` 后继续。

## 验证

```sh
make test-unit
make test-integration
make test
```

环境要求、分层运行和预处理专项命令见[项目测试规则](docs/unit-testing-guidelines.md)。测试使用合成资料和测试 Embedding；真实模型的语义质量、吞吐和容量需要单独用获准样本验证。旧开发表收敛和 knowledge_type 字段删除的区别见[迁移说明](docs/phase1/phase1-technical-design.md#7-验收与迁移)。
