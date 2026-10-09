# 项目测试与完成定义

本文维护测试环境、可执行命令与完成定义。公共行为以[首期技术设计](phase1/phase1-technical-design.md)为准，预处理规则与扩展契约以[文档预处理](phase1/preprocessing.md)为准。以下命令均从仓库根目录执行。

## 测试范围

使用 pytest、pytest-django，文件 `test_*.py`，函数 `test_<行为>`。测试真实业务结果与主要失败分支，不追求 100% 覆盖率，不为每个内部函数复制实现逻辑写断言。

- `tests/unit/`：离线验证输入与 DTO、预处理步骤／格式／结构／预算、Embedding 适配、中文分词、BM25 与 RRF。不要访问数据库、网络或真实模型。
- `tests/integration/`：独立 PostgreSQL 测试库验证导入、更新、权限、失败回滚、检索与 HTTP API。模型使用明确的测试替身；HTTP 协议可用本地临时服务验证。
- 不重复建设 contract/e2e/并发/升级矩阵。只有需求和风险确实增加时补相应测试。

## 编写规则

每个用例围绕一个行为，Arrange/Act/Assert 清晰。fixture 使用小型合成资料，不含真实维修记录和凭据。mock 外部模型或故障边界，不 mock 掉待验证的核心流程。断言内容、排序、持久化变化与错误行为，避免只检查“函数被调用”。

新增插件使用统一 DTO 合约测试；新增预处理步骤验证阶段与执行顺序，新增结构策略验证正文覆盖和父子边界；新增召回器验证过滤范围和候选结构；修改排序验证多路排序与去重。真实模型效果需另用小型真实样本验收，不能由 fake 向量测试代替。

## 环境准备与分层运行

1. 按 [README 本地运行](../README.md#本地运行) 创建 `.venv` 并安装开发依赖。pytest 使用 [tests/settings.py](../tests/settings.py)，提供明确的测试密钥和测试密码默认值；离线单测无需准备数据库或模型服务。
2. 先运行离线单测：

```sh
make test-unit
```

3. 运行集成测试前，准备专用 PostgreSQL 实例／账号。测试账号须能创建 Django 测试库，连接配置使用 POSTGRES_HOST/PORT/DB/USER/PASSWORD。可在首次准备时复制配置模板到被忽略的 `.env.test`，编辑为专用测试连接后加载：

```sh
cp .env.example .env.test
chmod 600 .env.test
# 编辑 .env.test，设置专用 PostgreSQL 测试连接
set -a; . ./.env.test; set +a
make test-integration
make test
```

集成测试使用模型替身，不需要下载或配置真实 Embedding。若本地没有 PostgreSQL，按 [Docker 自动测试](phase1/deployment.md#4-在-docker-中运行自动测试) 使用独立 itxia-tests 项目运行全量或指定测试；不使用运行服务的数据库和卷。

Makefile 默认使用 `.venv/bin/python`。已在其他虚拟环境安装依赖时，可通过 `make test-unit PYTHON=python` 指定解释器。退出码 0、所有用例通过才表示相应范围验收通过。

## 预处理专项验证

1. 验证格式适配、步骤编排、结构策略、长度预算和原文接线：

```sh
.venv/bin/python -m pytest \
  tests/unit/test_preprocessing_pipeline.py \
  tests/unit/test_preprocessing_parsers.py \
  tests/unit/test_preprocessing_strategies.py \
  tests/unit/test_preprocessing_chunking.py \
  tests/unit/test_raw_import.py -q
```

| 用例文件 | 重点检查 |
| --- | --- |
| [步骤编排](../tests/unit/test_preprocessing_pipeline.py) | 增删／调序确实生效，错误阶段和错误返回类型被拒绝 |
| [格式适配](../tests/unit/test_preprocessing_parsers.py) | 微信正文、嵌套粗体栏目、默认 alt“图片”视为缺失说明、BOM、表格与代码保真、显式解析器注册 |
| [结构策略](../tests/unit/test_preprocessing_strategies.py) | 单／多机型边界与机型名必填、评测检索块合并与断点、购机卡预算与全局限制、经验案例 |
| [长度预算](../tests/unit/test_preprocessing_chunking.py) | 计入父段标题、均分切分与过早断点、换行退回、表格按行切分与表头前缀、atomic 超限拒绝、tokenizer 替换和字符定位 |
| [原文接线](../tests/unit/test_raw_import.py) | 请求校验、统一编码／保存接口、权限与失败时不调用模型或保存 |

2. 在上节准备好的隔离 PostgreSQL 环境运行原文 API 集成测试：

```sh
.venv/bin/python -m pytest tests/integration/test_raw_ingestion.py -q
```

[原文集成用例](../tests/integration/test_raw_ingestion.py) 使用真实 Token API 和 PostgreSQL、明确的模型替身，检查三类文档导入／检索、重复与更新、预算切分、权限及失败保留已有文档。专项通过后，修改实现还需运行 `make test` 验证整个导入与检索链。

语雀专项的合成正文和快照均由测试代码生成，不提交真实原文：

| 用例文件 | 重点检查 |
| --- | --- |
| [语雀 Markdown](../tests/unit/test_yuque_markdown.py) | 方言规范化、行号保持与代码保真 |
| [章节策略](../tests/unit/test_sections.py) | 章节父段、子块与正文边界 |
| [增强步骤](../tests/unit/test_enrichment_steps.py) | 风险、时效提示与目录检索前缀 |
| [来源清单](../tests/unit/test_source_manifest.py) | 通用清单严格校验、单篇优先与最长目录前缀、元数据补丁；语雀仓库清单覆盖附录 74 篇、28 篇教程 |
| [快照导入](../tests/unit/test_yuque_importer.py) | OpenAPI 结构快照、语雀连接器身份与元数据、通用导入服务报告状态、逐篇失败继续、整批访问错误终止、命令试运行与启动错误；不访问数据库／模型 |
| [公众号采集连接器](../tests/unit/test_wechat_connector.py) | 永久链接、短链接与临时链接的身份规则，旁注校验，元数据，`import_wechat` 试运行、清单错误与整批终止；不访问数据库／模型 |
| [语雀 HTTP 边界](../tests/unit/test_yuque_openapi.py)、[语雀客户端](../tests/unit/test_yuque_client.py) | 不开 socket，替换 HTTP 边界验证网络／超时、响应格式、默认间隔、认证独立异常、快照失败与 Token 不进入错误消息 |
| [语雀集成](../tests/integration/test_yuque_ingestion.py) | 原文 API 与 `call_command` 快照导入、数据库保存与 reused、internal 权限、未登记／未接入不导入；隔离 PostgreSQL 与模型替身 |
| [语雀 OpenAPI](../tests/integration/test_yuque_openapi.py) | 本地 HTTP 服务模拟路径与认证头、分页、祖先路径、401／403 终止、单篇失败继续、列表失败、快照覆盖未接入类别并可离线读取、无 Token 启动失败与输出不泄露 Token；正式导入使用隔离 PostgreSQL 与模型替身 |
| [公众号采集集成](../tests/integration/test_wechat_ingestion.py) | `call_command` 导入评测与选购指南、可见性、身份与链接、reused；隔离 PostgreSQL 与模型替身 |

```sh
.venv/bin/python -m pytest tests/unit/test_source_manifest.py tests/unit/test_yuque_importer.py tests/unit/test_wechat_connector.py tests/unit/test_yuque_client.py tests/unit/test_yuque_openapi.py -q
# 需要上节配置的隔离 PostgreSQL
.venv/bin/python -m pytest tests/integration/test_yuque_ingestion.py tests/integration/test_yuque_openapi.py tests/integration/test_wechat_ingestion.py -q
```

沙箱禁止 socket 时，HTTP 集成与 PostgreSQL 全量测试由编排者在隔离环境运行，可先用 `--collect-only` 确认可收集。需真实语雀 Token 的接口实测、方言差异修正、目录 slug 核对、快照保存与教程验收待 Token 到位后补测，本地服务与模型替身不代表真实接口或语料质量验收通过。

3. 验证部署服务与真实模型时，按 [Docker 原文导入验收](phase1/deployment.md#35-验收原文预处理导入) 操作，检查返回完整父段与命中定位。真实文章还需人工检查标题识别、父子边界、测试条件／结果和图片补录；自动测试的通过不能证明真实语料划分与检索质量。

## 完成定义

功能完成需要：满足需求并接入入口；受影响旧功能回归及全量测试通过；必要文档同步。新增外部模型或来源能力，补充相应实际调用/样本验证；未做的验证明确标注，不声称通过。

仅整理文档时，核对实现状态、示例、文件链接、标题锚点和命令；记录实际执行的验证范围。文档中的历史通过数量不作为当前版本验收标准。
