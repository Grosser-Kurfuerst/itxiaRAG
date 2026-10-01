# Repository Guidelines

## 项目结构

当前仅有设计文档，尚无业务源码、测试目录、素材目录或构建脚本。

- `docs/requirements.md`：总体业务需求、边界和验收目标。
- `docs/technology-selection.md`：总体技术调研与选型理由。
- `docs/phase1/`：首期需求、技术设计和语雀／微信公众号接入方案。
- `docs/unit-testing-guidelines.md`：全项目通用测试规则和功能完成定义。

首期计划采用 Django 模块化单体、PostgreSQL 和单 Worker，提供知识检索与维护 API 和管理命令；正常资料自动质量放行，异常与新处理器样本人工复核，Django Admin 按需启用。Agent 和回答生成由外部应用负责。`docs/phase1/phase1-technical-design.md` 统一定义数据、API 和阶段契约；修改相关设计时同步文档引用。

## 开发与验证命令

目前没有应用启动或构建命令。用 `rg --files docs` 查阅文档；文档修改后检查表格、代码块、JSON 示例和本地链接。以下为实现阶段约定，当前不可运行：

```sh
python3 -m pytest tests/unit tests/contract
python3 -m pytest tests/integration
```

第一条运行离线测试，第二条需隔离 PostgreSQL 及必要扩展。阶段发布另按技术设计验收空库启动、升级、自动放行／异常复核和实际业务链路。

## 编码与命名

默认使用中文，除非明确要求其他语言。Markdown 文件名采用小写连字符，如 `source-ingestion-plan.md`；字段和命令用反引号。未来 Python 代码遵循 PEP 8、4 空格缩进，函数／变量用 `snake_case`，类用 `PascalCase`。目前未配置 formatter 或 linter，不虚构检查结果。

## 测试要求

计划使用 pytest、pytest-django，测试文件命名为 `test_*.py`，用例命名为 `test_<条件>_<结果>`。覆盖业务行为和主要失败分支，不追求 100% 覆盖率；单测不连接真实网络、数据库或模型。

功能完成须满足需求、接入实际入口、通过旧功能回归及全量单元／契约测试；按影响补充集成、模型效果或迁移验证。必需检查未完成时标记“验证未完成”。详细规则见 `docs/unit-testing-guidelines.md`。

## 提交与评审

按项目约定使用 `类型(范围): 简短描述`，例如 `docs(phase1): 明确查询字段`、`test(retrieval): 补充回归用例`。PR 说明目的、影响范围、关联需求／问题、验证命令及未验证项；接口变化同步文档，界面变化再附截图。当前工作区无法读取 Git 历史，上述格式来自项目约定。

## 协作与数据约束

- 设计兼顾扩展性与可维护性，避免无需求支撑的复杂抽象。
- 未明确要求时，不修改业务代码或 `.gitignore`；严格遵守忽略规则，不提交被忽略文件。
- 不提交凭据、私有附件或未脱敏维修记录；代码解释提供可跳转的文件链接。
- 优先专用工具，必要时使用 OpenCLI；自行查阅来源，不调用外部 AI 代替调研。
