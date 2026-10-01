# itxiaAgent 知识库

按 [迭代一实现方案](docs/phase1/phase1-iteration1-implementation.md) 逐步实现。当前完成范围见 [实施记录](docs/phase1/implementation-progress.md)。尚未包含笔吧推文、Worker 或模型。

## 本地启动

需要 Docker Engine、Compose v2 和 Make。镜像固定 Python 3.12／PostgreSQL 17 的 digest，安装依赖时需要访问镜像与包仓库，应用运行不访问外部平台。

将 `.env.example` 复制到仓库外的私有文件，例如 `/tmp/itxiaRAG.env`，用随机值替换两个密码占位并设置 `chmod 600`。不要把私有配置写进仓库。随后运行：

```sh
make up ITERATION=1 ENV_FILE=/tmp/itxiaRAG.env
make migrate ITERATION=1 ENV_FILE=/tmp/itxiaRAG.env
make test-unit ENV_FILE=/tmp/itxiaRAG.env
make test-integration ENV_FILE=/tmp/itxiaRAG.env
make acceptance ITERATION=1 STEP=S4 ENV_FILE=/tmp/itxiaRAG.env
```

服务仅监听 `127.0.0.1:18080`；可通过 APP_PORT 改端口。`/health/live/` 返回 200；S4 在迁移与配置就绪后 `/health/ready/` 返回 200，否则 503。现已开放短笔记导入、人工复核、发布、关键词检索、父／子引用和来源撤回。app 的容器健康检查只检查 live。

`make acceptance` 不指定 STEP 时验收最终 S6；请求未完成步骤会报错。验收通过真实 HTTP 调用运行中的服务，JUnit 报告在 app 容器 `/tmp/itxia-acceptance/`，可用 `docker compose cp` 导出到仓库外。`make test-unit` 在相同 Python 容器内执行全量离线单元／契约测试。

## 停止与恢复

```sh
make down ENV_FILE=/tmp/itxiaRAG.env
make up ENV_FILE=/tmp/itxiaRAG.env
```

down 保留数据库卷，重复 migrate 不删除数据。不要使用 `down -v` 处理需要保留的数据。调试数据库中断时，仅停止当前隔离 Compose 项目的 db，检查 live=200、ready=503 后重新启动 db；结构化日志记录 `database_unavailable`，不打印数据库凭据。

当前 Compose 的 app 使用 development 构建目标以运行测试；`docker build --target runtime` 只安装运行依赖。生产部署需另行配置 HTTPS 和私有环境变量。

## 初始化和账号（S1）

`make migrate` 执行累积迁移及 `kb_init`，幂等创建五张业务表、配置单例和无 Token／密码的 `kb-system` 审计账号。已有不同配置会报错，不能通过重跑初始化覆盖。

在 app 容器内执行以下部署侧命令；Token 文件只保存在受控文件路径中（权限 0600），终端不会打印密钥：

```sh
python manage.py kb_account --username maintainer --permissions maintain_source,review_import,read_internal --token-file /tmp/maintainer.token
python manage.py kb_account --username reader --permissions '' --token-file /tmp/reader.token
python manage.py kb_account --username maintainer --revoke-token
```

命令可通过 `docker compose --env-file /tmp/itxiaRAG.env -p itxia-phase1 exec -T app ...` 执行。账号默认无可用密码；已有账号权限不同会报冲突。Token 撤销后重新发放需使用新的文件路径。访问 API 使用 `Authorization: Token <token>`，schema 可指定 `Accept: application/vnd.oai.openapi+json`。不提供 Admin 或公开账号注册端点。

## 候选导入和报告（S2）

以下命令在 app 容器执行，使用合成样本；自己的文件先安全复制进容器，再指定容器内路径：

```sh
python manage.py kb_import --file fixtures/iteration1/basic.txt --metadata fixtures/iteration1/basic.json --actor maintainer
python manage.py kb_job --id <任务UUID> --actor maintainer --report /tmp/job-report.md
python manage.py kb_job --id <任务UUID> --actor maintainer --resume
python manage.py kb_job --id <失败任务UUID> --actor maintainer --retry
```

S2 正常导入退出码为 **4**，表示已构建但待人工复核；报告成功退出 0；非法输入为 2、任务失败／状态冲突为 3、依赖故障为 5。终端只输出 ID／状态；含原文的报告使用 0600 权限且拒绝覆盖已有文件。`resume` 恢复 pending 构建，成功产物不会重写；failed 必须显式 `retry`。没有后台队列。

HTTP 使用 `POST /api/v1/sources/`，请求为样本 metadata 加 `input_text`；更新使用 `POST /api/v1/sources/{id}/imports/`，只提交内容字段。正常同步处理均返回 200，仍须检查 `status`、`review_status` 和 `is_current`。通过 `GET /api/v1/import-jobs/{id}/` 查看固定输入、质量报告和父子预览。所有入口需要 Token，维护动作和 public/internal 范围分别检查。

只接受 `manual + generic_note.v1`、1–8000 字且不超过 200 行的 TXT／Markdown；保留 Markdown 行尾空格。`domain_metadata` 仅可省略或 `{}`，知识类型固定 concept。来源授权和脱敏须事先确认。同一稳定键和同文复用，来源管理字段不同或要求提高已有候选的人工复核要求时返回 409。维护模式拒绝新导入和恢复，任务报告仍可读。

## 人工发布和引用（S3）

先核对任务报告，再执行以下容器内命令；也可通过 `/api/v1/import-jobs/{id}/review/`（`{decision, note}`）和 `publish/`（`{}`）完成：

```sh
python manage.py kb_job --id <任务UUID> --actor maintainer --review approved --note "已核对完整原文与定位"
python manage.py kb_publish --id <任务UUID> --actor maintainer
python manage.py kb_withdraw --source <来源UUID> --actor maintainer
```

复核只记录结论，批准后仍需显式发布。发布指针与审计同事务提交；重复发布当前构建幂等，过时候选返回 409。`GET /api/v1/contexts/{id}/` 和 `/api/v1/evidence/{id}/` 只返回当前已发布资料；候选、旧引用、无权对象均 404。更新内容重新导入，新稿发布前保留旧稿可读。

`PATCH /api/v1/sources/{id}/` 只维护链接、授权、visibility 与 active／disabled；`POST /api/v1/sources/{id}/withdraw/` 幂等撤回，保留正文、指针和审计。public 可收紧为 internal，反向操作须另建已脱敏且获公开授权的来源。withdrawn 不可恢复。维护模式允许报告、停用和撤回，拒绝发布及读者详情；S3 自动放行清单仍为空。


## 关键词检索（S4）

已认证账号调用 `POST /api/v1/search/`，例如：

```json
{"query":"备份", "preprocess":"auto", "scenario":"general", "filters":{}, "top_k":5}
```

返回完整 `contexts` 和引用、实际配置 hash、`query_id`，不生成答案。连续中文按短语匹配，可用空格分隔关键词；本阶段只支持 general 与空 confirmed_context。`filters.source_ids`／`knowledge_types` 只缩小范围，普通账号看不到 internal 或未发布候选。

`preprocess=bypass` 跳过处理器，auto 默认 NoOp。未来适配器通过 `config.components` 注入，并须自行限制外部 I/O 超时；当前没有 LLM 或线程池。返回前再次复核权限与当前构建，64 KiB 预算不足时整父段跳过并返回 `context_incomplete`。`no_result` 表示正常未命中；空结果且降级时为 `insufficient_evidence`。S4 仍需人工批准并发布。
