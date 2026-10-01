# 实现进度

当前版本按最新请求从 S0～S6 收敛为最小混合检索知识库，原阶段发布和验收结果仅保留于 Git 历史，不代表当前契约。

- 已实现：标准化 DTO 导入、三表保存、稳定 key 更新、Token/visibility、真实 Embedding HTTP 适配器、关键词与精确向量检索、RRF、父段返回。
- 扩展点：SourceConnector、DocumentPreprocessor 注册表、DocumentStore、EmbeddingProvider、Retriever、Ranker、ContextReader，均通过组合根装配。
- 已删除：审核、自动放行、系统发布账号、发布/撤回/审计、任务恢复、复杂配置、健康探针、维护模式、Compose、演示脚本和原验收矩阵。
- 未实现：来源获取、文章解析、父子分段、查询预处理、回答生成。当前维护者提交已整理 JSON。
- 数据库：只在独立测试库验证新结构；未修改运行中的旧库。存在旧资料时迁移中止，使用新数据库并按 DTO 重新导入。

## 当前验证

- `make test-unit`：20 passed，不依赖模型和数据库。
- 隔离 PostgreSQL/本地 HTTP 测试环境运行 `python -m pytest -q`：30 passed（含上述 20 项离线测试）。
- `python manage.py check`：无问题；`python manage.py makemigrations --check --dry-run`：No changes detected。
- `git diff --check` 与本地 Markdown 链接检查通过。
- 尚未验证：真实 Embedding 模型的中文相关性、性能和真实笔吧样本。已有模型协议适配器不等于已完成模型效果验收。
- 独立只读评审第 1 轮：`NO_BLOCKING_ISSUES`；专用 reviewer 角色因模型不可用未启动，使用独立只读智能体完成同等评审。两项非阻塞建议已处理：清理 OpenAPI 依赖、明确召回路线名和排名协议。
- 精简 requirements 后，在 `/tmp` 干净虚拟环境重跑 20 项单测及 Django check，全部通过。仓库原有未跟踪 `pyproject.toml`、`uv.lock` 保持原样，不纳入本次变更。
