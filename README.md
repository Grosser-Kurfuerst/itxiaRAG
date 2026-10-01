# itxiaAgent 知识库

当前仓库实现的是一个可运行的最小混合检索知识库：调用方提交已经整理好的标准化文档，系统保存父段和子块，使用关键词与向量两路召回，经 RRF 排序后返回完整父上下文。文章抓取、解析、父子分段和最终回答由后续模块负责，当前没有 Agent 或审核发布流程。

详细契约见 [首期技术设计](docs/phase1/phase1-technical-design.md) 和 [迭代一实现](docs/phase1/phase1-iteration1-implementation.md)。合成请求见 [fixtures/iteration1/basic.json](fixtures/iteration1/basic.json)。

## 本地运行

需要 Python 3.12、PostgreSQL 和兼容 OpenAI `/embeddings` 协议的模型服务（本地或已获准的外部服务）。安装依赖：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

私有配置放仓库外：

```sh
cp .env.example /tmp/itxia.env
# 编辑 /tmp/itxia.env 的密钥、数据库连接和 Embedding 服务参数
set -a; . /tmp/itxia.env; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

必须配置 `EMBEDDING_BASE_URL`、模型名、维度和 revision；缺少时导入／检索返回 503，不使用伪向量代替语义模型。更换模型、revision 或 query 指令后须重新导入资料。`.env.example` 的模型名只是配置示例，不会自动部署或下载模型。

账号只通过部署侧创建：

```sh
.venv/bin/python manage.py kb_account --username maintainer --permissions maintain_source,read_internal --token-file /tmp/maintainer.token
```

导入接口需要 `maintain_source`：

```sh
curl -H "Authorization: Token $(cat /tmp/maintainer.token)" \
  -H 'Content-Type: application/json' \
  -d @fixtures/iteration1/basic.json \
  http://127.0.0.1:8000/api/v1/sources/
```

返回 `source_id`、`context_ids` 和 `reused`。更新同一来源时保留同 key 段落的 ID；相同内容返回 `reused=true`。Embedding 完成后才开启数据库事务，任意写入失败会回滚。

查询接口：

```sh
curl -H "Authorization: Token $(cat /tmp/maintainer.token)" \
  -H 'Content-Type: application/json' \
  -d '{"query":"电池能用多久","top_k":5}' \
  http://127.0.0.1:8000/api/v1/search/
```

普通账号只获得公开来源；`read_internal` 才能检索内部来源。Embedding 故障返回 502，不静默降级为空结果。

## 验证

```sh
make test-unit
make test-integration
make test
```

测试使用合成资料和测试 Embedding。真实模型的语义质量、吞吐和容量需要单独用获准样本验证。旧数据库存在旧版业务数据时，精简迁移会主动中止；请使用新数据库并按标准 DTO 重新导入，不要手工删除旧数据绕过检查。
