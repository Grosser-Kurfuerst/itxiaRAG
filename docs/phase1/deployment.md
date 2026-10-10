# Docker 部署与运行验收

从仓库根目录执行本文命令。Compose 提供 Django + Gunicorn、PostgreSQL，以及可选的 Ollama Embedding 服务。当前支持标准化 JSON 导入，以及 HTML／Markdown／文本经预处理后导入；文章抓取、OCR 和回答生成尚未实现。预处理策略与请求契约见[文档预处理](preprocessing.md)，测试规则见[项目测试规则](../unit-testing-guidelines.md)。

## 1. 准备配置

需要 Docker Engine、Docker Compose v2、`curl`。推荐先用本地 CPU 模型完成小规模验收；以下 Ollama 示例不需要 GPU。

```sh
mkdir -p .runtime
cp .env.example .env.docker
chmod 600 .env.docker
openssl rand -hex 32  # 用输出替换 DJANGO_SECRET_KEY
openssl rand -hex 16  # 用输出替换 POSTGRES_PASSWORD
```

编辑项目根目录下的 `.env.docker`，设置以下参数。该文件由 `.gitignore` 忽略，配置模板 `.env.example` 仍可提交：

```dotenv
DJANGO_SECRET_KEY=上面生成的密钥
POSTGRES_PASSWORD=上面生成的数据库密码
DEBUG=false
ALLOWED_HOSTS=127.0.0.1,localhost
POSTGRES_DB=itxia
POSTGRES_USER=itxia
EMBEDDING_BASE_URL=http://embedding:11434/v1
EMBEDDING_MODEL=qwen3-embedding:0.6b
EMBEDDING_DIMENSIONS=1024
EMBEDDING_REVISION=qwen3-embedding-0.6b-v1
EMBEDDING_API_KEY=
EMBEDDING_QUERY_PREFIX="Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "
```

`EMBEDDING_REVISION` 是部署者记录的模型版本标识，不会触发下载。记录 `ollama list` 的模型 ID；更新模型文件后应更新此标识。地址、模型、维度、revision 或 query prefix 改变后，需要重新导入资料。

检索门槛与原文输入预算为可选服务配置，可在同一环境文件中增加：

```dotenv
RETRIEVAL_MIN_COSINE=
RETRIEVAL_MIN_BM25=0
PREPROCESS_MAX_INPUT_BYTES=2400
```

默认不额外过滤向量，关键词保留 BM25 大于零的结果。设置最低 cosine 时范围为 `[-1, 1]`，最低 BM25 须非负；两路分别过滤。具体值应按实际问题集校准，改动门槛不需重新导入，只需重建应用容器。结果的 `matches[].route_scores` 保留原始 cosine／BM25，`score_kind` 说明当前排序分数，默认是 `rrf`。

PREPROCESS_MAX_INPUT_BYTES 控制原文入口完整 Embedding 文本的 UTF-8 字节预算，修改后重建应用容器。它不是精确 token 上限，也不会改变已导入子块；需要应用新切分预算时重新提交原文。目标 tokenizer 的注入方式见[输入预算与扩展](preprocessing.md#4-evidence-输入预算)。

为减少重复命令，在当前终端定义：

```sh
ITXIA_ENV="$PWD/.env.docker"
dc() { docker compose --env-file "$ITXIA_ENV" -p itxia "$@"; }
dc config -q
```

`config -q` 成功时没有输出。Compose 固定 Web 的数据库地址为 `db:5432`，配置文件中的 `POSTGRES_HOST`/`POSTGRES_PORT` 不影响容器连接。

## 2. 启动模型和知识库

先启动模型容器并下载模型，再启动 Web：

```sh
dc --profile model up -d embedding
dc exec embedding ollama pull qwen3-embedding:0.6b
dc exec embedding ollama list
dc up -d --build app
dc --profile model ps
```

首次下载和构建需要网络；模型文件与数据库分别存放在 `ollama_data`、`postgres_data` 卷。`db` 应为 `healthy`，`app`、`embedding` 应为 `running`。Ollama 容器默认使用 CPU；GPU 加速不包含在这份最小配置中。

如果已有兼容 OpenAI `/embeddings` 的服务，跳过 Ollama 两个启动／下载命令，配置实际地址、模型和维度，然后直接启动 `app`。容器里的 `127.0.0.1` 指向自身；宿主机服务可用 `http://host.docker.internal:8001/v1`，并确保它监听容器可达的接口。

Web 启动时先执行数据库迁移。检查应用、迁移和日志：

```sh
dc exec app python manage.py check
dc exec app python manage.py migrate --check
dc logs --tail=100 app db
```

`check` 应无错误，`migrate --check` 应退出成功。数据库首次使用新卷；旧版数据库仍有业务数据时，收敛迁移会中止，应保留旧库并在新库重新导入。

默认 API 只绑定宿主机 `127.0.0.1:8000`，PostgreSQL 和 Ollama 不暴露宿主机端口。端口冲突时在配置中增加 `APP_PORT=18000`，并同步下文请求地址。远程访问可通过 SSH 转发；对外部署时由 HTTPS 反向代理接入，并把域名加入 `ALLOWED_HOSTS`。

## 3. 验收导入与混合检索

### 3.1 创建维护者和普通调用账号

账号没有网页登录入口，Token 通过部署命令生成。复制 Token 到项目内被忽略的 `.runtime/`：

```sh
dc exec app python manage.py kb_account --username maintainer \
  --permissions maintain_source,read_internal --token-file /tmp/maintainer.token
dc cp app:/tmp/maintainer.token .runtime/maintainer.token
chmod 600 .runtime/maintainer.token
TOKEN_FILE="$PWD/.runtime/maintainer.token"

dc exec app python manage.py kb_account --username reader \
  --permissions '' --token-file /tmp/reader.token
dc cp app:/tmp/reader.token .runtime/reader.token
chmod 600 .runtime/reader.token
READER_TOKEN_FILE="$PWD/.runtime/reader.token"
```

### 3.2 验证认证

```sh
curl -sS -w '\nHTTP %{http_code}\n' \
  -H 'Content-Type: application/json' \
  -d '{"query":"续航"}' http://127.0.0.1:8000/api/v1/search/
```

预期 `401`。首页和 `/health/live/`、`/health/ready/` 返回 `404` 属于当前正常行为，不能用于验收服务故障。

### 3.3 导入标准化合成样本

```sh
curl -sS --fail-with-body -w '\nHTTP %{http_code}\n' \
  -H "Authorization: Token $(cat "$TOKEN_FILE")" \
  -H 'Content-Type: application/json' \
  --data-binary @fixtures/iteration1/basic.json \
  http://127.0.0.1:8000/api/v1/sources/
```

首次应为 `200`、`reused=false`，包含 `source_id` 和只有一项的 `context_ids`。重复执行应为 `200`、`reused=true`，ID 保持相同。样本是合成评测，不包含真实文章。

### 3.4 验证两路召回和父段返回

```sh
curl -sS --fail-with-body -w '\nHTTP %{http_code}\n' \
  -H "Authorization: Token $(cat "$READER_TOKEN_FILE")" \
  -H 'Content-Type: application/json' \
  -d '{"query":"续航怎么样","top_k":5}' \
  http://127.0.0.1:8000/api/v1/search/
```

预期：

- HTTP `200`，`mode=hybrid`，`result_status=found`。
- `contexts` 包含“笔记本 A”，`text` 同时包含续航和风扇噪声两句话，即返回完整父段。
- `contexts[].matches[].ranks` 中有 `keyword` 和 `vector` 两路名次；排名位于每个命中子块内。
- `matches` 只列出实际命中子块，包含 ID、key、定位、分数和各路名次；不会返回父段下未命中的子块列表。

再用“电池能用多久”查询，检查同义问法是否仍能找到续航资料；具体名次由真实模型决定。几条样本只验证接入和返回行为，不能代表完整语义质量。

### 3.5 验收原文预处理导入

提交下面的合成微信 HTML，验证格式解析、父子分段和公共导入链。标准化入口的示例无需修改：

```sh
curl -sS --fail-with-body -w '\nHTTP %{http_code}\n' \
  -H "Authorization: Token $(cat "$TOKEN_FILE")" \
  -H 'Content-Type: application/json' \
  --data-binary @- http://127.0.0.1:8000/api/v1/sources/raw/ <<'JSON'
{
  "source": {"source_type": "wechat", "canonical_locator": "synthetic:raw-smoke", "visibility": "public"},
  "preprocess": {"schema": "product_review", "version": 1},
  "raw": {
    "content": "<div id=\"js_content\"><h2>Laptop Raw</h2><p><strong>续航</strong></p><p>续航约 9 小时。</p><p><strong>噪声</strong></p><p>风扇较安静。</p></div>",
    "media_type": "text/html",
    "metadata": {"title": "合成原文评测", "entity_title": "Laptop Raw", "source_date": "2026-09-28", "author": "合成作者"}
  }
}
JSON
```

首次应返回 `200`、`reused=false` 和一项 context_ids；重复提交同一请求应为 `reused=true`，ID 不变。再执行 3.4 的查询，确认 contexts 包含 Laptop Raw，父段 text 同时保留续航和噪声；matches 的 locator 中 parent_char_start/end 应定位到 text 中的命中子块，end 为开区间。

购机指南、经验文档、长子块拆分、atomic 超限与失败行为通过[预处理专项测试](../unit-testing-guidelines.md#预处理专项验证)验证。真实文章的视觉排版和图片关键参数仍需人工核对。

### 3.6 验证维护权限

把 3.3 或 3.5 的 Token 换成 `$READER_TOKEN_FILE`，预期 `403`；普通账号可以检索公开来源，不能导入。公开／内部隔离和更新回归由下面的集成测试进一步验证。

### 3.7 语雀 OpenAPI 与快照导入

`.dockerignore` 白名单包含 `sources/`，镜像内提供语雀导入命令及 `sources/yuque/manifests/itxia.toml` 清单，另放行 `docs/phase1/yuque-ingestion/requirements-analysis.md`，供清单测试核对第一批文档清单；同时继续排除 `__pycache__` 和 `*.py[cod]`。

阶段 4 的读取与保存快照代码已实现；本节需要真实语雀 Token 的操作均待 Token 到位后补测，不代表已经完成接口实测、真实快照保存或 28 篇教程导入与检索验收。语雀 Token 与 3.1 的知识库 API Token 是两种凭据。

在被忽略的 `.env.docker` 中设置获授权的 `YUQUE_TOKEN`，`YUQUE_API_BASE` 可保留 `https://www.yuque.com/api/v2` 或留空使用默认地址。Compose 将这两项透传至 app；改配置后重建容器，不在命令行中传 Token：

```sh
dc up -d --build app
# OpenAPI 试运行：仅预处理教程，不编码或写入数据库
dc exec app python manage.py import_yuque \
  --manifest sources/yuque/manifests/itxia.toml --dry-run

# 保存完整分类快照后试运行；快照保存在容器 /tmp，随后复制到宿主机
dc exec app python manage.py import_yuque \
  --manifest sources/yuque/manifests/itxia.toml \
  --save-snapshot /tmp/yuque-openapi-snapshot --dry-run
dc cp app:/tmp/yuque-openapi-snapshot .runtime/yuque-openapi-snapshot

# 从刚保存的快照正式导入；需先创建具有 maintain_source、read_internal 的账号
dc exec app python manage.py import_yuque \
  --manifest sources/yuque/manifests/itxia.toml \
  --snapshot /tmp/yuque-openapi-snapshot --username maintainer

# 再执行同一命令，正文、元数据与流水线配置不变时应全部 reused
dc exec app python manage.py import_yuque \
  --manifest sources/yuque/manifests/itxia.toml \
  --snapshot /tmp/yuque-openapi-snapshot --username maintainer
```

复制快照时使用新的宿主机目标目录，避免 `dc cp` 将目录嵌套到已存在的同名目录内。容器重建会丢失 `/tmp` 快照，后续离线运行可在宿主机按 README 的 `--snapshot` 命令读取，或把已保存的目录复制回 app。正式导入去掉 `--snapshot` 就使用 OpenAPI；单篇重跑可加 `--only help/install_win10`，参数可以重复。

`--snapshot` 与 `--save-snapshot` 互斥，保存可与 `--dry-run` 同用。保存读取清单内所有知识库，写出 `toc.json`、合并所有分页的 `docs.json`（均为 `{"data": [...]}`）以及已分类正文；知识、工具、排障和案例虽未接入，仍保存正文，跳过和未登记只保留列表元数据。`--only` 只限制导入，不限制保存范围。检查报告中保存失败和缺失 slug；完整快照预期覆盖第一批 74 篇，实际目录与正文完整性待 Token 到位后补测。

未接入类别报告为 `skipped`，不写入数据库；快照正文读取失败无论类别或 `--only` 都记为 `failed`，继续保存其余文档，结束后非零退出。详情的 429、其他 HTTP／网络错误、超时或格式错误同样按单篇处理；401／403 终止整批并提示检查 `YUQUE_TOKEN` 与知识库权限。目录／列表失败在任何正文处理前终止整批；写盘错误也终止整批。没有重试队列，修正后重跑；保存失败的正文旧文件会删除，不能把不完整快照当作完整数据。

Token 不写入报告、日志或快照；快照含正文，和凭据一样不提交。重复导入仍可能调用 Embedding，`reused` 验证的是统一保存链的内容去重。真实教程验收与检索抽查见[阶段 4 验收](yuque-ingestion/implementation-phases.md#53-验收)。

## 4. 在 Docker 中运行自动测试

使用独立 Compose 项目 `itxia-tests`，避免触碰运行服务的数据库和卷。测试内部再创建 PostgreSQL 测试库；模型使用明确的测试替身，不需要启动 Ollama。

```sh
dct() { docker compose --env-file "$ITXIA_ENV" -p itxia-tests --profile test "$@"; }
dct run --build --rm test
```

退出码 `0`、全部测试通过为验收条件。需要排查某一层时，替换默认测试命令：

```sh
dct run --rm test python -m pytest tests/unit -q
dct run --rm test python -m pytest tests/integration -q
```

集成测试覆盖真实 PostgreSQL 保存、去重与更新、权限过滤、完整父段与命中定位、BM25 + 向量 + RRF、原文预处理导入、模型错误及 HTTP 模型协议。单独验证原文 API 时运行：

```sh
dct run --rm test python -m pytest tests/integration/test_raw_ingestion.py -q
```

测试通过后清理专用测试资源：

```sh
dct down -v
```

完成应用检查、上述导入／查询验收以及全量自动测试，才算系统运行验收通过。吞吐、容量和大量真实问题的检索质量需要另做样本验证。

历史验证范围：2026-10-03 曾在独立 Docker 项目用真实 `qwen3-embedding:0.6b` 验证合成样本的导入、去重、两路召回、同义查询、父段／命中定位、权限隔离和重启后的持久化。此记录不证明当前版本全量测试通过，也不代表真实文章质量；当前验收按上文命令重新执行，不沿用旧通过数量。

## 5. 常见问题与日常操作

| 现象 | 检查方式 |
| --- | --- |
| `app` 重启或无法启动 | `dc logs --tail=100 app db`；检查配置和迁移 |
| 导入／查询 `503` | 检查 Embedding 地址、模型名、维度、revision 是否齐全 |
| 导入／查询 `502` | 检查模型已下载、网络地址可达、返回维度匹配；本地模型看 `dc logs embedding` |
| 原文导入 `400` | 检查 schema、media_type、元数据与机型边界；ENTITY_TITLE_REQUIRED 表示单机评测缺少机型名，SEMANTIC_UNIT_TOO_LARGE 表示购机指南或经验文档的不可拆小节超预算，见预处理文档 |
| 查询 `no_result` | 确认已导入、资料可见、模型配置未变及路线门槛；模型配置改变后重新导入 |
| `401`／`403` | 分别检查 Token 和账号权限 |

更新代码后重建并查看日志：

```sh
dc up -d --build app
dc logs --tail=100 app
```

当前版本会自动执行 `0004_remove_evidence_knowledge_type`，只删除分类列；既有正文和向量保留，无需重新导入。旧导入 JSON 须去掉子块 `knowledge_type`，查询须去掉 `filters.knowledge_types`，否则返回 400。响应已取消全量 `citations`，通过 `matches[].key/locator` 查看命中定位。

备份数据库到被 `.gitignore` 忽略的 `.runtime/`，正常停止时保留数据卷：

```sh
dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > .runtime/backup.sql
dc --profile model down
```

`down -v` 会删除所选项目的数据卷，仅用于确认可丢弃的测试数据。真实部署不要这样清理。`.env.docker`、`.runtime/`、Token、备份和私有文章都不应提交。Ollama 示例使用 `latest` 便于试运行，长期部署可把镜像固定到已经验证的标签或 digest。
