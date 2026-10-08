# Repository Guidelines

## 项目结构

这是一个 Django + PostgreSQL 的最小混合检索知识库。`api/` 提供标准导入、原文导入和查询入口；`contracts/` 定义 DTO、协议和 Serializer；`ingestion/` 编排原文预处理与标准化文档导入；`catalog/` 保存来源、父段和子块；`embeddings/` 适配模型服务；`retrieval/` 实现关键词、向量和 RRF；`config/` 是组合根。测试在 `tests/unit/` 与 `tests/integration/`，样本在 `fixtures/iteration1/`，设计文档在 `docs/phase1/`。

API 接收已标准化的 `ProcessedDocument`，也支持将 HTML、Markdown 或纯文本经可编排预处理后导入。已实现评测、购机指南和经验文档的父子分段策略；当前不实现文章抓取、OCR、审核发布、任务队列、回答生成和知识图谱。文档入口见 [README](README.md#文档导航)，预处理契约与扩展方式见 [文档预处理](docs/phase1/preprocessing.md)。

## 开发与验证

```sh
make migrate
make run
make test-unit
make test-integration
make test
```

需要在环境变量提供 Django 密钥、PostgreSQL 连接和 Embedding 服务。未配置模型时接口返回配置错误；仅测试中使用明确的模型替身。

## 编码约定

Python 使用 4 空格缩进，函数和变量用 `snake_case`，类用 `PascalCase`。保持模块依赖方向：业务编排依赖 `contracts` 协议，不直接拼模型厂商请求；外部模型、保存、召回和排序通过适配器注入。不要为低概率场景增加复杂状态机或通用 Repository。

Markdown 文件名使用小写连字符。代码修改必须同步受影响的 `docs/phase1/` 契约和样例。

## 测试要求

单测不能访问真实数据库、网络或模型；集成测试使用隔离 PostgreSQL、合成资料和明确的模型替身。新增来源预处理器必须通过统一 DTO 合约；新增召回器必须验证权限过滤、候选结构和失败行为。真实模型质量需另做样本验证。

功能完成须接入实际 API、通过受影响回归和全量测试，并同步文档。不要提交凭据、私有文章、真实维修记录或构建缓存。

## 提交与评审

Commit message 使用 Conventional Commits，例如 `feat(retrieval): 增加混合召回与 RRF`、`docs(phase1): 简化迭代一方案`。PR 说明行为变化、受影响接口、验证命令和未验证项。
