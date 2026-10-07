# Docker 部署与运行验收

从仓库根目录执行本文命令。Compose 提供 Django + Gunicorn、PostgreSQL，以及可选的 Ollama Embedding 服务。文章抓取、解析、自动分段和回答生成仍不在当前实现中；导入使用已整理好的标准 JSON。

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

检索门槛为可选服务配置，可在同一环境文件中增加：

```dotenv
RETRIEVAL_MIN_COSINE=
RETRIEVAL_MIN_BM25=0
```

默认不额外过滤向量，关键词保留 BM25 大于零的结果。设置最低 cosine 时范围为 `[-1, 1]`，最低 BM25 须非负；两路分别过滤。具体值应按实际问题集校准，改动门槛不需重新导入，只需重建应用容器。结果的 `matches[].route_scores` 保留原始 cosine／BM25，`score_kind` 说明当前排序分数，默认是 `rrf`。

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

### 3.3 导入合成样本

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
- `matches` 只包含实际命中子块的 ID、key 和定位信息；不会返回父段下未命中的子块列表。

再用“电池能用多久”查询，检查同义问法是否仍能找到续航资料；具体名次由真实模型决定。几条样本只验证接入和返回行为，不能代表完整语义质量。

### 3.5 验证维护权限

把 3.3 的 Token 换成 `$READER_TOKEN_FILE`，预期 `403`；普通账号可以检索公开来源，不能导入。公开／内部隔离和更新回归由下面的集成测试进一步验证。

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

集成测试覆盖真实 PostgreSQL 保存、去重与更新、权限过滤、完整父段与引用、BM25 + 向量 + RRF、模型错误及 HTTP 模型协议。测试通过后清理专用测试资源：

```sh
dct down -v
```

完成应用检查、上述导入／查询验收以及全量自动测试，才算系统运行验收通过。吞吐、容量和大量真实问题的检索质量需要另做样本验证。

2026-10-03 已在独立 Docker 项目验证：全量 40 项测试通过；真实 `qwen3-embedding:0.6b` 的导入、去重、两路召回、同义查询、父段／引用和权限隔离检查通过。停止并重建容器后，Token、资料和模型文件保留且检索通过。此记录只覆盖合成样本。

## 5. 常见问题与日常操作

| 现象 | 检查方式 |
| --- | --- |
| `app` 重启或无法启动 | `dc logs --tail=100 app db`；检查配置和迁移 |
| 导入／查询 `503` | 检查 Embedding 地址、模型名、维度、revision 是否齐全 |
| 导入／查询 `502` | 检查模型已下载、网络地址可达、返回维度匹配；本地模型看 `dc logs embedding` |
| 查询 `no_result` | 确认已导入、资料公开或账号有内部权限，且模型配置未变；模型配置改变后重新导入 |
| `401`／`403` | 分别检查 Token 和账号权限 |

更新代码后重建并查看日志：

```sh
dc up -d --build app
dc logs --tail=100 app
```

备份数据库到被 `.gitignore` 忽略的 `.runtime/`，正常停止时保留数据卷：

```sh
dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > .runtime/backup.sql
dc --profile model down
```

`down -v` 会删除所选项目的数据卷，仅用于确认可丢弃的测试数据。真实部署不要这样清理。`.env.docker`、`.runtime/`、Token、备份和私有文章都不应提交。Ollama 示例使用 `latest` 便于试运行，长期部署可把镜像固定到已经验证的标签或 digest。
