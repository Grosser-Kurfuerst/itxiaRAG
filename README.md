# itxiaAgent 知识库

按 [迭代一实现方案](docs/phase1/phase1-iteration1-implementation.md) 逐步实现。当前完成范围见 [实施记录](docs/phase1/implementation-progress.md)。尚未包含笔吧推文、Worker 或模型。

## 本地启动

需要 Docker Engine、Compose v2 和 Make。镜像固定 Python 3.12／PostgreSQL 17 的 digest，安装依赖时需要访问镜像与包仓库，应用运行不访问外部平台。

将 `.env.example` 复制到仓库外的私有文件，例如 `/tmp/itxiaRAG.env`，用随机值替换两个密码占位并设置 `chmod 600`。不要把私有配置写进仓库。随后运行：

```sh
make up ITERATION=1 ENV_FILE=/tmp/itxiaRAG.env
make migrate ITERATION=1 ENV_FILE=/tmp/itxiaRAG.env
make test-unit ENV_FILE=/tmp/itxiaRAG.env
make acceptance ITERATION=1 STEP=S0 ENV_FILE=/tmp/itxiaRAG.env
```

服务仅监听 `127.0.0.1:18080`；可通过 APP_PORT 改端口。`/health/live/` 返回 200；S0～S3 尚无知识查询，`/health/ready/` 返回 503。S0 只提供这两个入口。app 的容器健康检查只检查 live，不把缺少查询能力误判成启动失败。

`make acceptance` 不指定 STEP 时验收最终 S6；请求未完成步骤会报错。验收通过真实 HTTP 调用运行中的服务，JUnit 报告在 app 容器 `/tmp/itxia-acceptance/`，可用 `docker compose cp` 导出到仓库外。`make test-unit` 在相同 Python 容器内执行全量离线单元／契约测试。

## 停止与恢复

```sh
make down ENV_FILE=/tmp/itxiaRAG.env
make up ENV_FILE=/tmp/itxiaRAG.env
```

down 保留数据库卷，重复 migrate 不删除数据。不要使用 `down -v` 处理需要保留的数据。调试数据库中断时，仅停止当前隔离 Compose 项目的 db，检查 live=200、ready=503 后重新启动 db；结构化日志记录 `database_unavailable`，不打印数据库凭据。

当前 Compose 的 app 使用 development 构建目标以运行测试；`docker build --target runtime` 只安装运行依赖。生产部署需另行配置 HTTPS 和私有环境变量。
