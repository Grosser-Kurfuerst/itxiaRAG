# itxiaAgent 知识库

当前仓库实现的是一个可运行的最小混合检索知识库：调用方提交已经整理好的标准化文档，系统保存父段和子块，使用关键词与向量两路召回，经 RRF 排序后返回完整父上下文。文章抓取、解析、父子分段和最终回答由后续模块负责，当前没有 Agent 或审核发布流程。

详细契约见 [首期技术设计](docs/phase1/phase1-technical-design.md)。合成请求见 [fixtures/iteration1/basic.json](fixtures/iteration1/basic.json)。

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

关键词路使用 jieba 分词与 Python BM25，向量路继续编码完整查询，最后由 RRF 融合。BM25 每次只读取当前可见子块并计算，内容更新立即生效；没有持久关键词索引或缓存，适合小规模验证。

## 验证

```sh
make test-unit
make test-integration
make test
```

测试使用合成资料和测试 Embedding。真实模型的语义质量、吞吐和容量需要单独用获准样本验证。旧数据库存在旧版业务数据时，精简迁移会主动中止；请使用新数据库并按标准 DTO 重新导入，不要手工删除旧数据绕过检查。

## 文档导航

每份文档只维护一类信息，变更时更新对应文档并引用，避免重复定义契约。

| 文档 | 内容 |
| --- | --- |
| [总体需求](docs/requirements.md) | 业务场景、当前范围、P1 扩展与 P2 自进化 |
| [技术选型与研究参考](docs/technology-selection.md) | 选择理由、替代方案、开源与论文依据 |
| [首期技术设计](docs/phase1/phase1-technical-design.md) | 模块、数据、API、错误行为及分步验收 |
| [来源接入说明](docs/phase1/source-ingestion-plan.md) | 当前资料准备、未来语雀／微信／维修记录插件 |
| [项目测试规则](docs/unit-testing-guidelines.md) | 通用用例要求、测试命令与开发完成定义 |
