# itxiaAgent 首期迭代一实现文档

版本：v0.4（迭代一实现基线，验收记录另列）
日期：2026-10-01  
依据：[首期技术设计](./phase1-technical-design.md)第 3～7 节及第 8.2 节 · [首期需求](./phase1-requirements-and-selection.md) · [项目测试规范](../unit-testing-guidelines.md)

本文定义“来源维护与关键词查询”迭代的开发清单、模块、数据、接口及验收。S0～S6 的实际实施和验证见 [实施记录](implementation-progress.md)，启动、演示与交接见 [运行手册](iteration1-runbook.md)。后续以本迭代通过验收的接口和迁移作为回归基线。

首期技术设计定义跨迭代的公共契约；本文补齐迭代一允许的子集和此前未定的实现参数。请求／响应最终由共享 DRF Serializer 校验并生成 OpenAPI，本文示例进入契约测试。修改公共契约时同时更新技术设计，不各自维护两套字段。

第 1～9 节定义迭代一最终状态；第 10.1 节按 S0～S6 拆分实际开发步骤，明确各步可用入口和验收边界。早期步骤尚未开放的能力不算已经交付。

## 1. 交付目标与能力边界

完成真实链路：**提交人工整理短文本 → 同步构建一父一子 → 自动放行或人工复核 → 发布 → 关键词查询 → 父子引用 → 更新／撤回**。Web/API 和 PostgreSQL 即可运行，不依赖未来模块。

| 范围 | 本迭代实现 | 本迭代不实现 |
| --- | --- | --- |
| 来源与输入 | `manual + generic_note.v1`，维护者提供完整短笔记；TXT 或作为原文保留的短 Markdown；知识类型固定 concept | 笔吧推文导入、评测 Schema、公众号／语雀读取、URL 抓取、平台格式转换、领域元数据投影和 conflicts 标注 |
| 构建 | 请求／命令内同步执行，保存 import_job；一个完整短笔记生成一个父段和一个子块 | 导入／解析 Worker、队列、定时任务、长文切分、多机识别、表格／图片抽取 |
| 维护 | 来源登记、任务状态／报告、自动放行、复核、发布、重试、停用／撤回 | 自定义网页后台、Admin 页面、来源历史查询、内容回滚、自动物理清理 |
| 查询 | general 场景，关键词／短语，来源与知识类型过滤，当前构建／权限筛选、完整父段返回 | 场景条件匹配、型号抽取、购机预算判断、维修诊断、语义召回、RRF、重排 |
| 扩展与观测 | 查询处理器接口、NoOp／bypass／异常回退、两类配置 hash、结构化 Trace | 智能意图识别、LLM、Agent、QueryRecord／Feedback、M6／图谱 |

**样本边界。** 使用社团自编或合成的通用短笔记，不把笔吧原文改标为 manual 来绕过来源范围。`source_type` 的公共枚举仍为 manual／yuque／wechat，但迭代一仅启用 manual；其他渠道和未注册 Schema 明确拒绝。

**本迭代固定限制。** 正文规范化后 1–8,000 个 Unicode 字符、最多 200 行；单次一个来源、一份正文。HTTP JSON 请求体最多 128 KiB，本地文件读取同样先限大小。超限要求维护者整理完整短笔记后提交，不静默截断。输入含多个主题的语义完整性由维护者确认，程序只验证可检测的格式、长度与关系，不宣称能识别任意复杂文档。

`generic_note.v1` 是通用笔记输入契约，初期处理器只支持整个短笔记一父一子。以后按小节切分可替换处理器并重建；不需要另造一次性的临时 Schema，也不能将 product_review 静默降级成通用笔记。

## 2. 工程基础与模块组织

### 2.1 新增工程文件

采用 Python 3.12、Django 5.2 LTS、DRF 3.16、psycopg 3、PostgreSQL 17。实现时在依赖锁文件和容器配置中固定验证过的补丁版本；当前锁文件与容器已固定实际验证版本，详见依赖文件和验收报告。

运行依赖为 Django、DRF、psycopg、Gunicorn、drf-spectacular；开发依赖增加 pytest、pytest-django、pytest-cov、pip-tools。用 `requirements.in` 声明直接依赖，生成包含精确版本的 `requirements.txt`；开发依赖同理。实现采用以下结构，不安装模型、Celery 或 PostgreSQL 搜索扩展：

```text
manage.py
config/
  settings.py                 # 环境变量、数据库、认证、日志
  urls.py                     # API、health、OpenAPI；不注册 /admin/
  wsgi.py
  components.py               # 装配默认解析器、处理器、检索后端
contracts/
  types.py                    # 请求内 DTO、父子草稿、Candidate
  serializers.py              # 严格请求／响应字段，供 API／命令共用
  errors.py                   # 领域错误及错误码
catalog/                      # 本迭代唯一自定义 Django app
  models.py
  migrations/
  services.py                 # 来源、任务、放行、发布、状态变更
  selectors.py                # 读者／维护者的可见对象查询
  policies.py                 # 动作权限、放行决策
  hashes.py                   # 输入和配置的规范化与 hash
  audit.py                    # 显式写 Django LogEntry
  management/commands/        # kb_init、kb_import、kb_job 等
ingestion/
  pipeline.py                 # 同步执行函数、草稿校验、持久化编排
  parsers.py                  # PlainTextParser：保留全文与行号
  processors.py               # GenericNoteProcessor
  registry.py                 # 固定的 Schema／实现版本映射
retrieval/
  query_processing.py         # NoOp、bypass、注入与回退
  keyword.py                  # ORM 候选查询和确定性排序
  service.py                  # SearchScope、组装与最终复核
api/
  views.py                    # 认证、调用、序列化、错误映射
  urls.py
profiles/iteration1/          # index.json、query.json、auto-release.json
fixtures/iteration1/          # 合成短笔记和维护请求元数据
tests/
  unit/
  contract/
  integration/
  e2e/
requirements.in
requirements.txt
requirements-dev.in
requirements-dev.txt
pytest.ini
Dockerfile
compose.yaml
.env.example
Makefile
```

管理命令必须放在已安装 app 的 `catalog/management/commands/` 中，并提供必要的 `__init__.py`。测试放仓库根目录 `tests/`，与项目通用命令一致。运行容器仅 app／db，附件服务和共享文件卷不启用；PostgreSQL 数据卷独立持久化。

### 2.2 模块改动点及依赖方向

| 新增模块／对应总体模块 | 具体开发内容 | 边界 |
| --- | --- | --- |
| config／M1 | Django 启动、环境配置、容器、Token、依赖装配和健康检查 | 不包含来源或检索业务规则 |
| contracts／M7 | DTO、严格 Serializer、公共错误；自动生成 OpenAPI | 不访问数据库，不调用服务 |
| catalog／M2 | 5 表、迁移、来源锁、去重、当前构建、权限、放行／审计 | 不解析正文、不拼 HTTP 响应；普通 ORM 即可，无通用 Repository |
| ingestion／M3、M4 的同步子集 | 纯文本解析、generic_note 处理器、草稿校验、同步运行与恢复 | 纯解析函数不写库；pipeline 编排可调用 ORM／catalog；无 Worker |
| retrieval／M5 | NoOp 与处理器协议、关键词排序、父段响应、返回前复核 | 不生成回答，不导入平台 SDK |
| api／M1、M7 | 路由、认证、错误映射、响应 Serializer | 不直接修改发布指针，不复制领域校验 |
| management／M1、M8 | 导入、报告、复核／发布、恢复、撤回、初始化和演示 | 共用 Serializer／领域服务，不能直接更新 Model 绕过规则 |
| tests／M8 | 离线、数据库、真实 HTTP 验收及报告 | 本阶段不用模型效果或最终首期命中率作为交付门槛 |

依赖方向：API／命令 → 应用编排 → catalog／纯解析／检索适配器 → PostgreSQL。`ingestion.pipeline.import_text` 组合提交、同步构建、放行和发布，catalog 不反向导入 ingestion。DTO 和严格校验不反向依赖 API。`config.components` 负责注入具体实现；模块导入不连接数据库、不读取源站。

## 3. 身份与访问规则

复用 Django 标准 User、Permission、Group 和 DRF Token，不增加用户表。API 均需 `Authorization: Token ...`，health 除外；生产经 HTTPS 访问。迭代一没有用户注册、网页登录或发放 Token 的公开端点，账号与 Token 由受控管理命令创建／撤销。

在 catalog app 声明自定义权限：`read_internal`、`maintain_source`、`review_import`、`manage_runtime`。普通账号只查询 public；授予 `read_internal` 的社员／内部服务可查 internal。维护者通常同时有 maintain_source、review_import，需要维护内部资料时另授 read_internal。Group 仅用于全局账号授权，不在来源上新增 allowed_groups；`is_staff` 不代表社员身份。

所有维护动作除动作权限外仍检查来源的 public／internal 范围；维护 selector 可查看候选、disabled 和 withdrawn 来源，但不能跨访问范围。无 Token 返回 401，无动作权限返回 403，有动作权限但对象不存在或不可见返回相同 404。

自动操作使用 `kb-system` 账号，设不可用密码且不发 API Token，仅授 read_internal、maintain_source、review_import，不设超级用户；只用于受控流程与审计。业务命令要求 `--actor`，在授权运维环境内运行，检查该账号权限；不能把自带账号名当作远程认证机制。初始化与账号配置命令限部署主机操作，承担首次账号引导，不能暴露为 HTTP 接口。

## 4. 数据模型与迁移

### 4.1 公共约定

除单例配置外，业务记录主键为服务端 UUID；时间为 UTC；日期为 ISO `YYYY-MM-DD`。字符串长度为字符数，JSON 必须通过共享校验器，不能用任意 JSONField 绕过 Schema。数据库枚举由 TextChoices 加 CHECK 约束；JSONField 默认用 callable `dict/list`。

创建 knowledge_source、import_job、context_unit、evidence_unit、retrieval_settings 共 5 表，通过 `Meta.db_table` 固定表名。Django auth、contenttypes、authtoken、admin LogEntry 依赖表另外创建，但不开放 Admin 路由。没有 source_version、独立构建／审核表、embedding 列、QueryRecord 或 Feedback。

### 4.2 `KnowledgeSource` → knowledge_source

| 字段 | Django 类型／默认值 | 规则 |
| --- | --- | --- |
| id | UUIDField，主键 | 服务端生成 |
| source_type | CharField(16) | 公共枚举 manual／yuque／wechat，本阶段提交只接受 manual |
| canonical_locator | CharField(200) | 必填，`manual:<稳定键>`，键只含字母、数字、连字符、下划线；不自动按正文生成 |
| source_url | URLField(2048)，null | HTTP(S) 阅读链接，仅保存、不访问 |
| visibility | CharField(8) | public／internal，提交必填 |
| authorization_status | CharField(12) | confirmed／pending／revoked；新建必须 confirmed |
| authorization_note | TextField | 必填 1–2,000 字，说明该可见范围的使用依据；不存密钥 |
| status | CharField(12)，active | active／disabled／withdrawn，由服务端设定 |
| current_build | FK ImportJob，null，PROTECT | 数据库列 current_build_id，发布服务验证归属本来源 |
| created_by | FK User，PROTECT | 登记者，仅作审计，不是逐来源所有权限制 |
| created_at／updated_at | DateTimeField | 服务端时间 |

唯一约束 `(source_type, canonical_locator)`。撤回终态不通过 PATCH 复活；disabled 可由有权维护者显式恢复 active，前提是授权仍 confirmed。只允许 public → internal 限权；internal → public 须另建已脱敏、已获公开授权的来源。调整授权为 pending／revoked 立即阻断查询与发布，不等待构建。

### 4.3 `ImportJob` → import_job

| 字段 | 类型／默认值 | 规则 |
| --- | --- | --- |
| id | UUID 主键 | 同时是 build_id |
| source | FK Source，PROTECT | 数据库列 source_id |
| base_build_id | UUIDField，null | 提交时当前指针的值；不设 FK，避免旧构建清理受阻 |
| content_hash | CharField(64) | 规范化输入 SHA-256，不是版本号 |
| input_text | TextField | 固定规范化正文，不可原地修改；限长在 Serializer 校验 |
| format | CharField(16) | txt／markdown；本阶段均保留原文，不转 HTML |
| title | CharField(200) | 必填 1–200 字，不依赖解析器猜标题 |
| author | CharField(200)，null | 未知为 null，非空值去首尾空白 |
| source_date | DateField，null | 原始日期，不能使用导入日期补齐 |
| source_metadata／domain_metadata | JSONField，默认 {} | 本阶段 Schema 见第 5 节 |
| document_schema／schema_version | CharField(64)／PositiveIntegerField | 本阶段 generic_note／1 |
| index_profile／index_profile_hash | JSONField／CharField(64) | 创建时固定活动配置及 hash |
| status／review_status | CharField(12)，pending | 构建 pending/running/succeeded/failed；放行 pending/approved/rejected |
| reviewed_by／reviewed_at | FK User(SET_NULL)／DateTimeField，null | 结论账号与时间；自动为系统账号 |
| quality_report | JSONField，默认 {} | 固定提交确认项、检查、待复核原因、放行方式与版本；服务端写入 |
| attempt_count／current_step | PositiveIntegerField(0)／CharField(32) | 尝试次数和失败位置 |
| error_code／error_detail | CharField(64)／TextField，null | 安全错误摘要，不保存堆栈或敏感正文 |
| created_by／created_at | FK User(PROTECT)／DateTimeField | 提交者与时间 |
| started_at／finished_at | DateTimeField，null | 最近一次构建的起止时间 |

不建 `(source_id, content_hash, index_profile_hash)` 全历史唯一约束；等价当前／候选在来源行锁内复用。索引：`(source_id, content_hash, index_profile_hash)`、`(status, created_at)`。stale、有效期等场景维护字段可在迭代三加列，本阶段只从 source_date 产生 date_unknown。

### 4.4 `ContextUnit`／`EvidenceUnit`

| 表 | 必需字段 | 约束 |
| --- | --- | --- |
| context_unit | id UUID；build FK ImportJob(CASCADE)；ordinal 正整数；title Char(200)；body Text；scope_fields JSON对象；locator JSON对象；field_sources JSON数组；warnings JSON字符串数组；knowledge_types JSON字符串数组 | `(build_id, ordinal)` 唯一，ordinal≥1；本阶段一条 ordinal=1 |
| evidence_unit | id UUID；context FK ContextUnit(CASCADE)；ordinal 正整数；knowledge_type／evidence_role／context_role Char(32)；body Text；retrieval_text Text；locator JSON对象；structured_fields JSON对象；warnings JSON字符串数组 | `(context_id, ordinal)` 唯一，ordinal≥1；本阶段一条 ordinal=1 |

父段保存 build_id，子块只保存 context_id，通过父段取得构建。两者都不重复保存 source_id、visibility 或放行状态。父段至少一子，本阶段必须恰好一父一子，由写入前／发布前校验保障；跨表来源归属由事务服务校验，不用无效的跨表 CHECK 声称数据库已保证。

`scope_fields` 为 `{}`，`field_sources=[]`；子块 `structured_fields` 固定为 `{"applicability":"unknown"}`。缺少设备信息不代表通用适用。子块 knowledge_type 固定 concept，父段 knowledge_types 固定 `["concept"]`；陈述角色固定 source_statement，context_role 固定 main。正文原样保留，retrieval_text 使用确定性模板，二者不能混为一列。

### 4.5 `RetrievalSettings` → retrieval_settings

单例 `id=1`（PositiveSmallIntegerField 主键及数据库 CHECK），index_profile／query_profile 为 JSONField 对象，各自 hash 为 CharField(64)，updated_at 为 DateTimeField。QueryProfile 必须引用同一个 index_profile_hash。配置缺失／hash 错误时 ready 和查询返回 503，不使用代码里另一套隐式默认值。

迁移顺序：先创建不带 current_build 的 Source，再创建 ImportJob，再补 current_build 外键，最后创建父子与配置表。不把示例账号、Token、业务样本写进数据迁移；由 `kb_init` 和 `kb_seed_demo` 分别初始化。迁移中不得出现 vector 字段、扩展创建或模型下载。

## 5. 迭代一输入与处理契约

### 5.1 固定输入 Schema

首次提交 `POST /api/v1/sources/` 使用扁平 JSON。来源字段按第 4.2 节；以下为内容字段，更新入口 `/sources/{id}/imports/` 只接受本表字段：

| 字段 | 必填／默认值 | 校验 |
| --- | --- | --- |
| title／input_text／format | 必填 | 标题、正文限制见前文；format=txt/markdown |
| author／source_date | 可省略，默认 null | author 非空字符串或 null；source_date 为有效 ISO 日期或 null |
| document_schema／schema_version | 必填 | generic_note／整数 1；不接受布尔值、数字字符串 |
| source_metadata | 默认 {} | manual 只允许空对象，不能用未知键夹带渠道身份 |
| domain_metadata | 默认 {} | 只允许省略或空对象；非空对象、null 和其他类型返回 400 INVALID_ARGUMENT |
| redaction_confirmed | 必填 boolean true | 维护者已确认输入适于声明的范围；false 不接收正文，返回 400 REDACTION_REVIEW_REQUIRED |
| require_manual_review | 默认 false，boolean | 只增加人工复核要求，不能用 false 取消服务端待复核项 |

本迭代由处理器固定写入 `evidence_unit.knowledge_type=concept`，不允许调用方通过顶层字段或 domain_metadata 指定知识类型。保留 domain_metadata 列和公共接口位置，但仅存 `{}`，不从中生成父子字段、检索文本或查询标记。完整知识类型枚举仍用于查询过滤校验。

`conflicts` 标注、conflict_key 投影、冲突标记计算和其他领域元数据投影推迟到后续迭代。即使提交 `{"knowledge_type":"concept"}` 或 `{"conflicts":[]}` 也属于非空 domain_metadata，应拒绝，不静默忽略。

所有顶层和嵌套对象拒绝未知键，JSON 对象不接受 null；不隐式转换字符串、数字和布尔值。非正文字符串去首尾空白后再校验长度；source_url 可省略为 null，创建来源的 source_type、canonical_locator、visibility、authorization_status、authorization_note 必填。不允许提交 profile、hash、状态、quality_report、父子 ID 或权限角色。来源授权、脱敏确认是维护者声明，不等于系统已自动证明授权与脱敏充分。

### 5.2 规范化与 hash

正文只去除文件开头的 BOM、统一 CRLF／CR → LF、移除首尾空白行。Markdown 保留各保留行的行尾空格和制表符，包括表示强制换行的两个空格；TXT 同样保留，复用一套保真规则。不对整篇正文或每行使用 strip／rstrip，不压缩中间空行、不改变缩进、不做 NFKC 或数字替换。首尾空白行指空行或仅含空格／制表符的行，按行判断后移除，不修改其他行。规范化后再校验字符数、行数并保存；行号为整理文本的 1-based 行号，区间两端均包含，不声称定位到原站页面。

content_hash 输入严格为：input_text、title、author、source_date、document_schema、schema_version、source_metadata、domain_metadata。省略值先补本文默认值；日期用 ISO 字符串，JSON 使用 UTF-8、键排序、紧凑分隔符和禁止 NaN 的固定序列化。domain_metadata 固定为 `{}`，省略和显式 `{}` 等价，不回写 concept。format 通过后文 IndexProfile 的两种格式同一保真解析保证产物语义相同，后续格式算法分化需相应配置变更。保留的行尾空格参与 hash：例如 `"第一行  \n第二行"` 与 `"第一行\n第二行"` 不得合并为相同输入。

来源 URL、授权、visibility、提交时间、redaction_confirmed 和 require_manual_review 不参与内容 hash；来源／权限变更仍通过发布前检查和审计生效。重复提交相同当前构建不会因为 require_manual_review=true 重新审核在线内容，响应明确 reused/is_current；如要暂停在线内容，应使用停用操作。未发布任务复用原来的复核要求；新请求要求人工复核而原任务未要求时，返回 409 REVIEW_REQUIREMENT_CONFLICT，指引先查看／复核已有任务，不自动发布以替代本次请求。

### 5.3 最小解析器与处理器

稳定入口沿用 `parse_and_chunk(ImportInput, IndexProfile) -> ProcessedDocument`。`FormatParser.parse(ImportInput) -> ParsedDocument` 和 `DocumentProcessor.process(ParsedDocument, DocumentProcessContext) -> ProcessedDocument` 用轻量 Protocol 定义，DTO 字段沿用技术设计第 2.5、2.6 节，在 contracts/types.py 统一声明。注册表以 `(parser_id, parser_version)`、`(processor_id, processor_version)` 查找实现；配置中未注册的标识必须报错，不能选“最新版”。

`PlainTextParser` 把规范化全文作为一个 text block，记录 title、line_start=1、line_end=N；Markdown 标题、列表、代码和表格按原文保留，不构造 AST、不渲染 HTML、不拆段、不识别产品对象。

`GenericNoteProcessor.process(ParsedDocument, DocumentProcessContext)` 输出：

- 一个父段：ordinal=1、title=输入标题、body=全文、scope_fields={}、field_sources=[]；locator=`{content_hash, spans:[{heading_path:[title], line_start:1, line_end:N}]}`。
- 一个子块：ordinal=1、body=全文、knowledge_type=concept、evidence_role=source_statement、context_role=main；locator 带同一 hash 和完整行区间。
- structured_fields 固定为 `{"applicability":"unknown"}`，父段 knowledge_types 固定为 `["concept"]`；不读取 domain_metadata 做领域投影，不生成 conflict_key。
- 日期未知加入“原始日期未知”资料 warning。没有自动私密信息识别或领域抽取，不为默认字段捏造原文依据。

处理器是纯 Python 实现，不访问 ORM／网络、不分配持久化 ID、不批准内容。同步 pipeline 分配父子 UUID，验证草稿，生成 `retrieval_text=title + "\n" + body` 并写库。不得加入 wechat／笔吧分支。缺失日期是非阻断警告，不强制转人工。

### 5.4 固定配置与放行资格

IndexProfile 至少包含 schema_version、document_processing 中 format→parser 和 document_schema/version→processor 的映射、各实现版本、规范化规则版本、正文字符／行数上限、父子 Schema 版本、retrieval_text 模板版本、lexical_backend=postgres-keyword-v1；tokenizer／embedding 为 null。本阶段 txt/markdown 都映射到同一保真解析器。

QueryProfile 至少包含 schema_version、index_profile_hash、query_processing 的 noop-v1／timeout_ms、keyword tokenizer／scorer 版本、candidate_limit=100、max_terms=16、response_context_bytes=65536、top_k 默认 5／上限 20；模型、RRF、重排为空。默认预处理预算 50ms，实际 NoOp 不进行等待或模型调用。

落地配置采用以下固定键名；index 中的映射值均为 `{id, version}`，版本初始为 `1.0.0`，不得只写无法追踪的类名：

| 文件 | 键与初始值 |
| --- | --- |
| index.json | `schema_version=1`；`document_processing.format_parsers` 的 txt／markdown 均指向 plain-text；`document_processing.schema_processors` 的 generic_note.v1 指向 generic-note；`normalization_version=1`；`max_body_chars=8000`；`max_body_lines=200`；`context_schema_version=1`；`evidence_schema_version=1`；`retrieval_text_template_version=1`；`lexical_backend=postgres-keyword-v1`；`tokenizer=null`；`embedding=null` |
| query.json | `schema_version=1`；`index_profile_hash` 由初始化命令注入计算值；`query_processing={processor_id: noop-v1, timeout_ms: 50}`；`keyword={tokenizer_version: 1, scorer_version: 1, candidate_limit: 100, max_terms: 16}`；`response_context_bytes=65536`；`default_top_k=5`；`max_top_k=20`；`embedding=null`；`rrf=null`；`reranker=null` |
| auto-release.json | `schema_version=1`；`entries[]` 每项含 document_schema、schema_version、index_profile_hash、sample_report、confirmed_by；无匹配项不具备自动放行资格 |

配置从受版本管理的 `profiles/iteration1/` 读取，补默认值后校验，再计算 SHA-256，表示为 64 个小写十六进制字符。QueryProfile 引用**实际算出的**索引 hash，例子中的重复字符不能作为配置身份。部署凭据和地址不参与 hash。

自动放行清单按 `generic_note/1 + index_profile_hash` 记录已验收样本报告和确认人。默认资格需由维护者在代表样本检查后确认；未在清单中时构建可成功但必须人工复核。演示仅使用随版本验收过的合成样本配置，不提供跳过硬校验的开关。更新清单不改变索引 hash，但放行记录须保存清单 hash。

## 6. 同步导入、去重与状态完整性

### 6.1 服务入口与事务划分

| 服务函数／文件 | 职责 |
| --- | --- |
| `submit_import(validated_input, actor)`／catalog/services.py | 校验动作与来源范围、活动配置，锁来源去重，提交固定任务；返回 task + reused，不在函数内解析 |
| `run_import_job(job_id, actor, retry=False)`／ingestion/pipeline.py | 仅对 pending 或显式重试的 failed 任务同步构建，成功产物不可重写 |
| `try_auto_release(job_id)`／catalog/services.py | 检查资格与硬校验；有待复核项则保持 pending，否则记录 auto 结论；既有 manual 结论不被改写 |
| `review_job(job_id, decision, note, actor)`／catalog/services.py | 只处理 succeeded/pending，记录 manual approved/rejected |
| `publish_build(job_id, actor)`／catalog/services.py | 统一发布事务；自动与人工均调用，不直接更新指针 |
| `resume_import(job_id, actor)`／ingestion/pipeline.py | 恢复中断的 pending 构建或 succeeded 的放行／发布；不绕过 rejected 或人工 pending |

采用三个短事务，不把整个 HTTP 请求设置为 ATOMIC_REQUESTS：

1. **T1 提交。** 校验请求与授权后，取得／创建来源并锁行，去重，创建 pending 任务并提交。把 redaction_confirmed_by、requested_manual_review 固定写入 quality_report；重试保留这两个确认项，不从新请求重新推断。稳定键并发创建由数据库唯一约束及 get_or_create 的冲突处理收敛，不产生两份来源。
2. **T2 构建。** 锁任务行，检查仍可执行；在事务内设置 running、增加次数，执行有严格长度上限且无外部 I/O 的纯解析，校验并写一父一子，设置 succeeded。此处短 CPU 工作允许持有行锁；未来 Worker／模型阶段必须重新划分事务，不能照搬长事务。构建异常回滚产物，在独立短事务重新锁任务，记录 failed／次数／步骤／安全错误；若另一调用已成功，则不得覆盖 succeeded。数据库本身不可用时只能返回 503 并记日志，不能保证错误状态已经落库。
3. **T3 放行／发布。** 调用 M2 记录自动结论并执行发布检查，成功切换指针；人工 pending 保持候选。写发布指针和对应审计必须同事务提交，失败保留旧构建。

进程在 T2 中断时事务回滚为 pending（原失败任务回到原 failed），不会留下持久化 running 或半套父子产物。因此本阶段无需租约、心跳或 Worker 恢复扫描。T1 后／T2 后中断，可用 `kb_job --resume` 恢复；T3 失败只记发布错误，不将 succeeded 改 failed，不删除已成功产物。

### 6.2 去重、重试与发布

首次来源 POST 命中已有稳定键时，先检查可见范围；不可见统一 404。来源字段与当前记录不一致时返回 409 SOURCE_METADATA_CONFLICT，不借重复导入覆盖授权、链接或 visibility；先经 PATCH 显式维护，再导入内容。更新入口不接收这些来源字段。

随后在来源锁内按 source_id、content_hash、index_profile_hash 检查；等价 rejected 任务优先拒绝，以下候选复用不包含 rejected：

- 当前完整构建等价：复用，200、reused=true，不新建任务。
- base_build_id 仍有效的等价 pending／succeeded 候选：复用；pending 可在当前请求继续同步执行，succeeded 只补做自动放行／发布，不重写产物。
- 等价 failed：返回已有任务状态，需显式 retry；不会每次 POST 偷偷增加重试次数。
- 同来源保留的相同输入／配置曾人工 rejected：409 REVIEW_REJECTED，要求修订后提交，不通过换 UUID 自动放行。
- 只有已清理历史摘要或已过时候选：允许新任务；无全历史内容唯一约束。

retry 端点只接受 failed，固定原输入／配置，成功任务重试返回 409。正文或算法改变须新任务；本阶段没有网络调用，不实现自动退避重试。`resume_import` 仅是恢复中断步骤，不能重试 failed 或拒绝任务。

发布前锁来源再锁任务，各管理服务遵守相同顺序；T2 仅锁任务，不再获取来源锁，避免反向锁依赖。检查归属、操作者范围、来源 active／授权 confirmed、任务 succeeded／approved、父子完整和活动索引 hash；若已是当前构建，幂等返回，不再比较 base_build_id。尚未发布时再检查 base_build_id 与当前指针一致，自动结论另复查自动放行资格，然后切换指针。检查失败返回对应 409，不能用再次发布恢复已撤回来源。

### 6.3 质量与复核

自动硬检查：非空正文、Schema／配置正确、父子数量与归属、ordinal、hash／行号、retrieval_text、知识类型和产物字段合法。硬检查失败只能 failed，人工不能强制批准。

构建成功后，quality_report.requested_manual_review=true 或配置未验收时保持 review_status=pending；资料日期未知等普通 warning 仍可自动发布。授权 pending／revoked 或 redaction_confirmed=false 在保存正文前拒绝，不创建含该正文的任务；不能把未授权内容先入库再等审核。保存后授权被撤销时由当前来源状态立即阻断。

质量报告最小形态如下。它由服务端生成，不是请求体：

```json
{
  "checks": {"schema": "passed", "parent_child": "passed", "locator": "passed"},
  "blocking_errors": [],
  "review_reasons": [],
  "warnings": ["原始日期未知"],
  "redaction_confirmed_by": 1,
  "requested_manual_review": false,
  "review_method": "auto",
  "release_policy_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "processor_id": "generic-note",
  "processor_version": "1.0.0",
  "review_note": null
}
```

review_method 在未决定时为 null，人工操作记录 manual 及必填说明；reviewed_by／reviewed_at 在任务列保存。redaction_confirmed_by 为提交账号 ID，requested_manual_review 为已校验请求值；二者创建后不变，其余报告字段按阶段补充。每次登记、放行、复核、发布、限权、撤回、重试都显式写 LogEntry，并与相应状态变更同事务提交，不能依赖不存在的 Admin 页面自动生成审计。只保存 ID、状态变化和简短原因，不复制正文、Token。样本验收与日常抽查关注内容覆盖和出处，程序校验不代表来源观点正确。

## 7. 关键词检索与引用

### 7.1 查询入口和早期能力校验

先按技术设计第 6.2.1 节完整校验 query、preprocess、scenario、confirmed_context、filters、top_k 的字段类型、枚举和 null 规则；再执行迭代一能力检查：

- scenario 省略或 general，confirmed_context 省略或 `{}`：允许。
- purchase／repair 或非空 confirmed_context：400 `CAPABILITY_NOT_AVAILABLE`，field_errors 指明 scenario／confirmed_context；不忽略用户约束后返回似乎匹配的结果。此限制在迭代三条件模块上线后解除。
- filters.knowledge_types 和 source_ids 全部支持；本迭代资料类型均为 concept，合法过滤集合未包含 concept 时正常无结果，不意味着其他类型的导入处理器已上线。过滤只读取证据类型字段，不读取 domain_metadata。

NoOp 透传文本和场景，未传场景设 general／default，显式 general 为 caller；auto 返回 noop，bypass 返回 bypassed；suggested_context={}。正常 NoOp／bypass 不算降级。

保留处理器依赖注入和编排回退：fake 可返回改写以验证调用链，正式配置仅启用 NoOp。异常、非法输出、超时或空改写回退原查询，status=fallback、execution.status=degraded。bypass 不调用注入处理器；处理器不得改变身份、filters、top_k 或显式场景。实现可用受控超时封装，测试用 TimeoutError fake，不部署线程池／模型服务仅为 NoOp 计时。

### 7.2 SearchScope 与确定性排序

使用共享 selector 构造数据库范围：来源 active、authorization_status=confirmed、visibility 在账号范围内、父构建 ID 等于 source.current_build_id、任务 succeeded／approved、活动 index_profile_hash；再交集过滤 source_ids 和知识类型。不存在与无权来源过滤效果相同，不返回隐藏来源计数。

关键词后端实现 `search(query, scope, limit) -> Candidate[]`；迭代一的 `build(build_id, index_profile) -> BuildSummary` 仅核对 retrieval_text 已完整写入并报告数量，不另建全文索引。后端固定为 PostgreSQL 参数化 ORM 查询，不启用全文／向量扩展：

1. 查询文本去首尾空白；正文与检索都不做 NFKC，以免查询转换而数据库表示未转换。采用 icontains 的大小写不敏感匹配。
2. 空白／中英文逗号、句号、问号、分号等分隔词项；型号中的连字符、下划线和点保留。中文连续文字作为一个词，不声称支持中文语义分词。按首次出现顺序去重，最多 16 项；超限以整段查询作为唯一短语项，不偷偷截断否定或型号。
3. 使用“完整查询短语命中 OR 任一词项命中”取得可见候选；纯标点没有有效词项则正常 no_result。`%`／`_` 等通过 ORM 参数化并按字面匹配，不作为 SQL 通配符。
4. 在**数据库中**用 Case／When 计算分数：完整短语命中 +100；每个唯一词项在 retrieval_text 命中 +10、在父段 title 命中另 +20。按总分降序、evidence_id 升序排序后才 LIMIT 100，不能先任取 100 条再排序。
5. 候选统一返回 evidence_id、retriever=keyword、rank 和原始分数。按排序聚合 context_id，父段取最佳子块名次，不累加子块数量。即使本阶段只有一子，也使用同一聚合接口，为迭代二复用。

“电脑很卡”不会自动分成“电脑”和“卡”；演示采用实际短语或空格分隔关键词。不承诺本阶段达到完整首期语义检索 ≥90% 的目标。关系 FK／状态索引用于约束过滤，普通 B-tree 不会优化任意 icontains；小样本采用顺序扫描基线，后续用 PGroonga／FTS 替换 keyword 后端。

### 7.3 父段响应和最终复核

批量取父段、任务和来源，避免逐候选查询。返回技术设计第 6.3 节完整 `contexts[]` 单项结构：context_id、title、text、scope_fields、source_id/source_title/source_url、build_id/content_hash、source_date/source_type、document_schema/schema_version、knowledge_types、locator、field_sources、matched_evidence_ids、citations、match_status、warnings、flags。

本阶段 text=父段 body；范围为空，不加模型补充；match_status=uncertain，对应未证明适用范围。日期 null 时父段和全局 flags 含 date_unknown。本迭代不计算或返回 conflict 标志；未返回该标志不表示已经检查且不存在来源冲突。

完整父段含全部子块引用，按 ordinal 排序；matched_evidence_ids 为实际命中子集。父段完整内容的 knowledge_types 必须都在显式允许集合内。按 top_k 最多返回父段，另以紧凑 JSON 的 contexts UTF-8 序列化大小限制 64 KiB；超预算整段跳过，继续下一候选，标记 context_incomplete，不截断正文／引用。

返回前再次批量复核来源权限、授权、状态和 current_build_id，失效候选移除并标记 execution=degraded；不重跑整次查询，不向用户说明被隐藏的对象身份。撤回事务已提交后的新查询必须不可见；不能承诺追回此前已经发送的字节。date_unknown 等资料标志仅从最终返回内容汇总。

顶层字段固定：UUID query_id、两类实际 hash、feedback_available=false、execution.mode=keyword、query_processing、result_status、flags、missing_conditions=[]、contexts。结果状态遵循：非空完整父段 → found；空且降级／context_incomplete → insufficient_evidence；正常空 → no_result。没有条件能力的请求已在入口拒绝，不用空 missing_conditions 冒充检查通过。

父段详情返回单项结构并省略 matched_evidence_ids。子块详情返回 evidence_id、context_id、body、knowledge_type、evidence_role、context_role、locator、structured_fields、warnings、所属父段对象 context；不返回内部 ranking 分数。两种详情都重新检查当前构建／权限，无权、旧 ID、撤回或不存在统一 404。

## 8. API、错误与管理命令

### 8.1 本迭代端点

| 方法与路径 | 权限 | 行为／成功状态 |
| --- | --- | --- |
| POST /api/v1/sources/ | maintain_source | 来源字段＋内容字段；同步处理与任务复用均返回 200 |
| POST /api/v1/sources/{id}/imports/ | maintain_source | 仅内容字段，复用同来源权限；同步处理与任务复用均返回 200 |
| GET /api/v1/import-jobs/{id}/ | maintain_source 或 review_import | 200，状态、报告、输入、候选父子预览；额外检查来源可见范围 |
| POST /api/v1/import-jobs/{id}/review/ | review_import | `{decision: approved/rejected, note: 非空字符串}`；200，不自动发布 |
| POST /api/v1/import-jobs/{id}/publish/ | maintain_source | 空对象；200，approved 候选统一发布，当前构建幂等 |
| POST /api/v1/import-jobs/{id}/retry/ | maintain_source | 空对象；仅 failed，同步重试后 200 返回实际任务状态 |
| PATCH /api/v1/sources/{id}/ | maintain_source | 只接受 source_url、authorization_status/note、visibility、status；按第 4.2 节检查 |
| POST /api/v1/sources/{id}/withdraw/ | maintain_source | 空对象；200，幂等撤回，不清空当前指针、不删除正文 |
| POST /api/v1/search/ | 已认证 | 200，关键词 contexts 响应 |
| GET /api/v1/contexts/{id}/ | 已认证 | 200，当前可见父段 |
| GET /api/v1/evidence/{id}/ | 已认证 | 200，当前可见子块及父段 |
| GET /api/schema/ | maintain_source | 200，Serializer 生成的 OpenAPI；不提供网页 UI |
| GET /health/live/、GET /health/ready/ | 无需 Token | 200／503，简要状态，不输出连接串与依赖明细 |

不注册反馈端点，访问返回 404；不创建查询记录表。上述维护请求也严格拒绝未知键与错误 JSON 类型。PATCH 不得修改 canonical_locator、source_type、正文、构建、放行状态；status 只接收 active／disabled，withdrawn 通过专用动作设置；空 PATCH 返回 400。说明字段最多 2,000 字。PATCH 与 withdraw 返回来源对象：id、source_type、canonical_locator、source_url、visibility、authorization_status/note、status、current_build_id、created_at/updated_at，不返回原文。

本迭代导入在请求内同步执行，正常返回任务结果时统一使用 **HTTP 200**，新任务与复用任务相同；不根据任务的 succeeded／failed／pending 状态选择 HTTP 状态码。200 表示本次同步操作已处理并返回结果，不等于构建成功或已经发布，客户端仍须检查 status、review_status、is_current 和 error_code。正常构建完成后 status 为 succeeded 或 failed；构建成功待人工复核表示为 status=succeeded、review_status=pending。

接收前的校验、去重冲突按对应 HTTP 错误返回；接收后预期构建失败或自动发布冲突返回 200 和实际任务结果。非预期异常、必要依赖故障仍返回 500／503；显式 publish 的冲突返回 409。中断留下的 status=pending 不代表存在后台队列，仍使用 resume 恢复。迭代二真正引入 Worker、异步接收新任务后再使用 202，客户端按返回的任务标识查询状态。

### 8.2 请求与响应示例

以下为合成样本，授权说明只用于演示：

```json
{
  "source_type": "manual",
  "canonical_locator": "manual:demo-basic-001",
  "source_url": null,
  "visibility": "public",
  "authorization_status": "confirmed",
  "authorization_note": "社团自编合成样本，允许公开试用",
  "title": "电脑维护基础",
  "author": "演示维护者",
  "source_date": null,
  "format": "txt",
  "input_text": "电脑维护应定期备份重要文件。\n操作前先确认备份可恢复。",
  "document_schema": "generic_note",
  "schema_version": 1,
  "source_metadata": {},
  "domain_metadata": {},
  "redaction_confirmed": true,
  "require_manual_review": false
}
```

任务提交、retry、review、publish 的统一简要响应如下；GET job 另包含 input（第 5.1 节内容字段，不含一次性确认参数）、quality_report、contexts（父段及 children 子块预览）、current_step、attempt_count、created_at/started_at/finished_at 和 error_detail。预览是维护权限对象，不调用只读当前发布内容的详情 selector。is_current 由当前来源指针计算，不另存发布状态列；它不替代来源的查询可见性判断。简要 error_code 优先返回构建错误，否则返回 quality_report.publish_error.code，没有错误为 null；发布成功须清除先前的 publish_error。

```json
{
  "source_id": "00000000-0000-0000-0000-000000000001",
  "import_job_id": "00000000-0000-0000-0000-000000000002",
  "build_id": "00000000-0000-0000-0000-000000000002",
  "status": "succeeded",
  "review_status": "approved",
  "review_method": "auto",
  "is_current": true,
  "reused": false,
  "error_code": null
}
```

查询例子：`{"query":"备份","preprocess":"auto","scenario":"general","confirmed_context":{},"filters":{},"top_k":5}`。其 contexts 含上例全文及完整行区间；返回 hash 和 UUID 必须来自实际记录，不能写死示例值。将该请求、预期身份关系和字段集合放入契约测试，不用整份随机 UUID 快照断言。

### 8.3 错误处理

统一使用技术设计第 6.4 节：request_id、error.code/message/retryable/field_errors，字段路径为点号形式。预期业务错误映射如下：

| 场景 | HTTP／任务处理 | 错误码与边界 |
| --- | --- | --- |
| 非法字段／未知 Schema／不可用来源渠道 | 400，不创建任务 | INVALID_ARGUMENT，指明字段路径 |
| 超 HTTP 体积／规范化正文长度 | 413／400，不创建任务 | INPUT_TOO_LARGE，正文不截断 |
| 未实现的场景／条件能力 | 400，不运行检索 | CAPABILITY_NOT_AVAILABLE |
| 未确认授权／脱敏 | 400，不保存提交正文 | AUTHORIZATION_REQUIRED／REDACTION_REVIEW_REQUIRED |
| 候选硬校验失败／配置实现缺失 | 保存 failed；同步提交返回 200 和实际失败状态 | CONTENT_SCHEMA_INVALID／IMPORT_CONFIGURATION_ERROR；不可人工批准 |
| 来源重复登记但管理字段不同／复用任务的复核要求不同 | 409，不修改已有任务或来源 | SOURCE_METADATA_CONFLICT／REVIEW_REQUIREMENT_CONFLICT |
| 发布过时／配置不符／来源不允许发布 | 显式发布为 409，自动流程写任务响应；旧构建不变 | BUILD_CONFLICT／PROFILE_CONFLICT／SOURCE_NOT_PUBLISHABLE |
| 人工拒绝的等价输入／错误状态动作 | 409 | REVIEW_REJECTED／INVALID_JOB_STATE |
| 数据库／权限查询失败 | 503，事务回滚 | DEPENDENCY_UNAVAILABLE，不伪装为空结果 |
| 自动放行清单损坏／缺失或系统账号异常 | 503，已成功构建的父子保留，可修复后 resume | RELEASE_POLICY_UNAVAILABLE／SYSTEM_ACCOUNT_UNAVAILABLE |
| 已自动批准但尚未发布的任务资格失效 | 显式 publish 为 409；导入／resume 返回实际任务结果并保留旧构建 | AUTO_RELEASE_NOT_QUALIFIED；清单撤销资格不自动撤回已发布内容 |
| 服务处于维护窗口 | 503 | MAINTENANCE |
| 非预期实现异常 | 500，安全 request_id | INTERNAL_ERROR；能安全保存时记录 failed，不暴露堆栈 |

任务成功后的发布失败在 quality_report 留安全发布错误，返回响应或恢复命令报告，不删除成功父子产物。详细 Trace 写入失败不否定已校验的查询结果；来源／发布审计失败则管理事务不能提交。

### 8.4 命令与退出码

命令位于 catalog/management/commands；容器内运行示例：

```sh
python manage.py kb_init --profiles profiles/iteration1
python manage.py kb_account --username maintainer --permissions maintain_source,review_import,read_internal --token-file /tmp/itxia-maintainer.token
python manage.py kb_import --file fixtures/iteration1/basic.txt --metadata fixtures/iteration1/basic.json --actor maintainer
python manage.py kb_job --id "<job-id>" --actor maintainer --report /tmp/job-report.md
python manage.py kb_job --id "<job-id>" --actor maintainer --review approved --note "已核对完整原文与定位"
python manage.py kb_job --id "<job-id>" --actor maintainer --resume
python manage.py kb_publish --id "<job-id>" --actor maintainer
python manage.py kb_withdraw --source "<source-id>" --actor maintainer
```

kb_init 限受控部署环境，幂等创建权限、系统审计账号和缺省活动配置；已有不同配置不能覆盖，需显式维护升级。不自动创建可公开登录的默认维护者密码。

kb_account 是部署侧账号命令：新账号设不可用密码；`--permissions` 只接受第 3 节的四个权限，空列表表示普通查询账号，已有账号不隐式覆盖权限。`--token-file` 创建 Token 并写权限 0600 文件，不打印密钥；`--revoke-token` 撤销已有 Token，两选项互斥；删除 Token 后再次发放生成新值。不能为 kb-system 发 Token。`kb_seed_demo` 复用该逻辑准备测试账号；不新增权限网页或公开账号 API。

kb_import 读取 UTF-8 文件，将正文放入 input_text，与 API 使用同一 Serializer。metadata 保存来源与内容参数，不再包含 input_text；更新时 `--source` 指定已有来源，metadata 只用内容字段。不保存上传路径。kb_job 的 `--report`、`--review`、`--resume`、`--retry` 四种模式互斥；retry 只处理 failed。复核要求 review_import，其他变更要求 maintain_source，报告读取同样需检查来源范围。kb_publish 允许人工／自动 approved 构建，统一服务负责恢复与幂等。

命令退出码：0=请求动作成功（导入已发布）；2=输入非法；3=任务失败／发布冲突；4=任务已接收但待人工复核；5=必要依赖不可用。报告命令成功写出即 0，任务状态仍写在报告中；不能把报告成功等同于发布成功。终端打印 ID、状态、错误码，正文只写入显式指定且受控的报告文件。只读数据库账号可供 DBeaver／pgAdmin 排查，不作为维护写入接口。

## 9. 启动、配置与阶段升级

.env.example 只列变量及安全占位：DJANGO_SECRET_KEY、DEBUG、ALLOWED_HOSTS、数据库地址／库名／用户／密码、PROFILE_DIR、KB_MAINTENANCE。密码／Token 不进入仓库或验收报告。若没有忽略规则，不自动修改 .gitignore，应使用仓库外的私有 env 文件并遵守现有忽略约束。

Makefile 实现上位设计的统一入口，迭代一只接受 ITERATION=1，其他值明确报未实现，不能加载空壳服务：

```sh
make up ITERATION=1
make migrate ITERATION=1
make seed-demo ITERATION=1
make acceptance ITERATION=1
make down ITERATION=1
```

以上为最终交付入口。up 启动 PostgreSQL 和 Django，允许迁移前 live 正常、ready=503；migrate 运行累积迁移与 kb_init，查询能力已实现且依赖就绪后 ready=200。seed-demo 在显式演示环境创建普通／内部／维护账号和合成样本，Token 保存在受控本地文件；重跑不重复来源或任务、不撤销用户已做的撤回。acceptance 使用真实 HTTP／命令和 PostgreSQL 输出报告；down 默认保留数据卷，清空须单独明确命令。

ready 校验数据库、5 表、活动配置 hash、关键词 selector 可执行、非维护状态；不检查不存在的 Worker／模型。KB_MAINTENANCE 开启时查询、父子详情、新导入、重试／恢复和发布返回 503；任务报告与停用／撤回仍可用，live 保持 200。日志包含 request_id/query_id、账号 ID、来源／任务／父子 ID、两类 hash、耗时、状态和错误码，不默认存原 query／正文／Token。

迭代一是首次应用交付，从上一外部迭代升级记“不适用”；内部 S0～S6 仍按第 10.1 节验证相邻步骤升级、同版本重启与重复迁移。后续迭代用累积迁移加 Worker／词法扩展／向量列，不重建来源身份；产物算法变化按技术设计第 4.4 节维护窗口完成重新构建，不能假设新处理器直接兼容旧 hash。本迭代从 S2 开始使用固定 IndexProfile，线上更新仅限新内容；查询调参和未来索引升级的完整操作工具按对应迭代交付。

## 10. 开发任务与验收标准

### 10.1 分步实现方案

S0～S6 是迭代一内部的开发步骤，不是首期四个迭代的替代编号。按“增加一项能通过真实入口使用的能力”推进，API、管理命令、测试和操作说明随对应能力一起交付。S0／S1 可运行的是基础服务与初始化；S2 起能维护真实资料；S3 能按 ID 读取已发布资料；S4 起能完成关键词查询；S6 才代表迭代一交付完成。

#### 10.1.1 通用执行与验收约定

- 每步固定源码提交或镜像版本，保存该步的依赖锁和累积迁移。下一步在已有数据上升级；不用删除数据库、跳过迁移或给最新程序传开关来模拟历史版本。
- 每步运行全部**已有**单元／离线契约测试、本次涉及的 PostgreSQL 集成测试，以及已开放入口的真实 HTTP／命令验收。业务样本必须经导入入口创建，不能直接插表代替业务链路；数据库约束和故障注入仍可在集成测试中构造。
- 已交付的行为持续回归；新模块的权限、事务、错误处理随首次开放入口实现，不留到 S6 补。尚未提供的路由不注册（404），OpenAPI 只包含实际可用端点，不能用固定空结果伪装查询成功。
- S0～S3 尚不具备关键词查询，`live=200` 表示 Web 进程存活，`ready=503` 表示知识查询尚未就绪；维护命令／已开放维护 API 仍可运行。S4 起依赖与配置正确时 `ready=200`。Compose 启动只等待数据库健康和 app 存活，不能因早期 ready=503 阻止维护服务启动。
- 每步先验收空库，再验收上一**内部步骤**升级及同版本重启。S0 无前一步；S1 保留框架数据和账号；S2 起保留来源、任务与父子 ID／hash；S3 起还须保留发布指针、来源状态与审计。未改变内容算法时不得因为升级重新导入或重新分配 ID。

沿用第 9 节的启动命令，增加仅供验收的 STEP 参数，例如验收 S3：

```sh
make up ITERATION=1
make migrate ITERATION=1
make acceptance ITERATION=1 STEP=S3
make down ITERATION=1
```

`up/migrate` 始终启动当前版本并执行它的全部迁移；S0 只需框架迁移，S1 起 migrate 同时调用 kb_init。`STEP` 仅选择“截至此步已交付能力”的验收范围，不改变服务行为、配置、路由或迁移。`make acceptance ITERATION=1` 默认 S6；早期版本请求尚未完成的步骤须非零退出，不能跳过缺失功能后报成功。历史步骤中的“尚未开放接口”只在对应版本验证；后续版本应新增正向验收，保留原有权限拒绝等长期规则。

`tests/e2e/iteration1/` 按能力存放验收用例，Makefile 用简单清单关联 STEP 与用例，不引入工作流框架。每步生成报告，记录版本、配置 hash（引入配置后）、环境、操作与结果、回归范围和当前能力边界；缺少必需检查时标记“验证未完成”。测试及报告入口从 S0 开始提供，S6 只做完整交付核对。

| 步骤 | 新增能力 | 当步使用入口 | 当前边界 |
| --- | --- | --- | --- |
| S0 服务启动 | Web、PostgreSQL、健康检查、测试与验收脚本 | up/migrate/down、live/ready | 暂无业务数据和账号管理 |
| S1 初始化与身份 | 5 表、Profile、Token 和动作权限 | kb_init、kb_account、受限 OpenAPI | 可初始化与管理账号，暂不能提交资料 |
| S2 候选导入与查看 | 同步一父一子、去重、报告、构建重试／恢复 | 导入 API／kb_import、任务 GET／kb_job | 所有候选待复核，尚未提供发布或读者查询 |
| S3 发布与引用 | 人工复核、原子发布、按 ID 读取、更新和撤回 | review/publish、contexts/evidence GET、来源 PATCH/withdraw | 能按 ID 读取；尚无关键词查询，自动放行未启用 |
| S4 关键词检索 | NoOp／bypass、关键词排序、完整父段及权限复核 | search + 已有维护／引用入口 | 可完成手动发布后的查询，仍不自动放行 |
| S5 自动放行与运行恢复 | 已验证配置自动发布，成功构建的中断恢复 | 原导入入口、自动放行清单、resume | 达到迭代一全部业务能力，无 Worker／模型 |
| S6 整体验收 | 演示、升级、故障与文档交接 | seed-demo、完整 acceptance | 全量通过才算迭代一交付 |

#### 10.1.2 S0：服务能启动、问题能定位

**实现范围。** 新增 manage.py、config、依赖锁、Docker／Compose、.env.example、Makefile、日志和健康端点；搭建 tests 与验收报告入口。数据库与 app 使用真实进程，不需要业务表、Token、Admin 或查询处理器。

**验收标准：**

1. 空环境执行 up、框架 migrate 后 app/db 可用；live 返回 200，ready 返回 503；此时没有 `/api/schema/` 或业务路由。
2. 停止测试数据库后 app 的 live 仍返回 200、ready 返回 503；恢复数据库不需要重新构建镜像。依赖状态通过内部日志可定位，响应不包含连接串或密码。
3. down 后数据卷仍在，重新 up 可运行；已有启动／健康检查测试和 `acceptance STEP=S0` 通过。产出最小运行说明。

#### 10.1.3 S1：能初始化存储与维护账号

**实现范围。** 新增 catalog 的 5 表及迁移、config 认证、权限声明、审计写入封装、动作权限与 visibility 策略；实现 Profile 校验／hash、kb_init、kb_account 和受维护权限保护的 OpenAPI 端点。Serializer／领域错误按该步入口需要引入，后续共享；不预先提供来源 CRUD 空壳。

**验收标准：**

1. 空库 migrate＋kb_init 创建 5 张业务表、系统审计账号和配置单例；hash 重算一致；重复执行不增加配置行、不覆盖已存在的不同配置。
2. kb_account 创建普通、内部、维护账号，Token 文件权限正确；维护 Token 可访问 schema，无 Token 返回 401，普通 Token 返回 403；撤销 Token 后原 Token 不能继续访问。内部读取资格由 read_internal 决定，不能由 is_staff 替代。
3. 真实 PostgreSQL 验证稳定来源键、ordinal、单例、FK 约束；权限策略离线验证，实际资料隔离在 S2／S3 验证。此时仍无资料提交入口，不宣称已通过来源查询验收。
4. 从 S0 升级后健康端点和已有框架数据正常，重复迁移及 S0 的适用回归通过；ready 仍为 503。

#### 10.1.4 S2：能提交短笔记并查看真实父子产物

**实现范围。** 实现导入 Serializer、正文规范化／content_hash、纯解析器／处理器／注册表、T1/T2 事务、来源去重与审计。同步交付两个导入 POST、任务 GET、失败任务 retry、kb_import、kb_job 的 report/retry/resume。自动放行清单保持空，报告说明配置未获自动放行资格；本步只生成待复核候选，不切 current_build_id。

本步 resume 只恢复构建；对 succeeded 候选直接返回当前待复核状态，不调用未实现的发布功能。S3 提供显式 publish，S5 再将成功构建的放行／发布恢复接入 resume。

**验收链路：** `API 或 kb_import → 同步构建 → GET job 或 kb_job --report`。

1. 已获准 manual 短笔记返回 HTTP 200，`status=succeeded`、`review_status=pending`、`is_current=false`；报告展示实际入库的一父一子，body、定位、固定 concept、空 domain_metadata 符合第 5 节。初次导入命令退出码为 4，表示已构建但待复核，不能误报为任务失败。
2. API 与命令使用相同 Schema；未确认授权／脱敏、非空 domain_metadata、非法渠道／Schema、超长输入返回明确错误且不写正文。Markdown 两个行尾空格、缩进、hash 验收通过。
3. 同一来源／输入／配置复用同一任务与父子 ID；正文或日期改变创建新候选。不同账号读取内部任务报告符合 visibility 和动作权限；普通账号不能用任务预览接口读取候选。
4. 集成测试注入处理错误时回滚全部产物，任务可记录 failed；同步 API 返回 200 和失败状态。failed 只经 retry 重试；T2 中断留下 pending 后，`kb_job --resume` 能完成构建；成功产物不会被重写。不能提供绕过硬校验的生产测试开关。
5. 重启后任务与父子仍在；S1 初始化、Token 与权限回归通过。发布／读者详情／搜索尚未注册，不能以接口不存在来宣称业务权限过滤已经验证。

#### 10.1.5 S3：能人工发布、按 ID 读取并撤回

**实现范围。** 实现 review_job、publish_build、来源 PATCH/withdraw 与审计，交付对应 API、kb_job --review、kb_publish、kb_withdraw；实现当前构建 selector、contexts/evidence 详情及响应 Serializer。自动放行清单继续为空，以人工发布闭合资料使用链路。

人工放行用于这个中间版本的可运行演示，不改变最终“正常资料自动放行、异常才复核”的目标；S5 完成后按完整策略验收。

**验收链路：** `导入 → 维护预览 → review approved → publish → GET context/evidence → 更新或撤回`。

1. 发布前读者详情返回 404；通过复核仍未发布时保持不可见；发布后 public 可由普通账号读取，internal 仅有内部读取资格的账号可见。无权、旧 ID、不存在对象返回相同 404，候选预览只供有权维护者。
2. approved 候选经统一服务切指针；重复发布当前构建幂等；rejected 或 failed 不能发布，retry/resume 不能改写拒绝结论；失败不影响当前已发布内容。
3. 发布新稿前旧 ID 仍可读，新稿发布后旧 ID 404、新 ID 可读；两个候选基于同一 base_build 时，后发布的过时候选返回 409。用真实数据库事务验证原子切换和审计失败回滚。
4. 停用、撤回、public→internal、授权撤销后详情立即按当前规则阻断；disabled 可按约束恢复，withdrawn 不可复活，internal 不得直接扩大到 public。
5. 从 S2 升级保留原候选的 ID/hash，可直接复核发布；用成功构建后中断的候选验证无需重做产物即可发布。本步验收的是详情可见性；搜索可见性到 S4 验收。

#### 10.1.6 S4：能通过关键词检索完整父段

**实现范围。** 实现完整查询 Serializer、NoOp／bypass／失败回退、SearchScope、keyword backend、父段聚合与预算、最终权限复核、查询 Trace 及 search 端点。复用 S3 已验证的引用结构；依赖和配置就绪时开放 ready=200。

**验收链路：** `导入 → 人工复核发布 → POST search → 使用返回 ID 读取引用 → 撤回后再查询`。

1. 通过已有入口准备至少三份含“备份”的合成笔记：公开已发布、内部已发布、未发布候选。普通账号只召回公开资料，内部账号增加内部资料；候选始终不参与查询，source_ids／knowledge_types 过滤不扩大权限。
2. 同分结果稳定，数据库先排序再 LIMIT，top_k 计父段；返回 text 与完整父段一致，matched_evidence_ids 是 citations 的子集；concept 之外的合法单类型过滤得到正常空结果，不返回 conflict 标志。
3. query_id、真实两类 hash、mode=keyword、feedback_available=false 齐全；NoOp/bypass 正常，fake 处理器异常按契约回退；正常空结果与降级空结果分别为 no_result／insufficient_evidence。fake 只用于协议测试，不替代端到端真实检索。
4. 父段预算不足时整段跳过；更新、撤回、限权及返回前状态变化都遵守当前构建规则；未知字段报 400，合法 purchase/repair 或非空 confirmed_context 报 CAPABILITY_NOT_AVAILABLE。
5. 从 S3 升级后既有发布资料可直接检索，父子 ID 与 index_profile_hash 不变；数据库不可用、配置损坏或维护模式使 ready／查询返回 503，不能伪装为空结果。S2/S3 的导入、复核、引用与撤回回归通过。

#### 10.1.7 S5：正常导入自动发布，中断后能恢复

**实现范围。** 在已有硬校验、人工发布和恢复基础上启用完整 try_auto_release；维护者核对代表样本后登记自动放行资格，接入导入／retry／resume 的 T3 编排。补齐成功构建后放行／发布中断的恢复、清单失效的再检查、自动操作审计及错误报告。原子性和权限必须沿用 S2/S3 的实现，不在本步才补。

**验收标准：**

1. 已验证配置的正常短笔记经 API 或 kb_import 同步自动发布；API 为 200，命令退出码 0，`approved/auto/is_current=true`，立即能查询，无须调用方逐篇 review/publish。
2. require_manual_review=true 或配置未获资格时保持待复核；date_unknown 不阻止自动发布；硬错误仍为 failed；非空 domain_metadata 仍被拒绝。人工批准／拒绝结论不被自动流程覆盖。
3. S2 已验收的 pending/failed 恢复继续通过；新增 T2 成功但 T3 未完成、自动 approved 尚未切指针等中断场景。resume 复用原父子产物并重新检查发布条件；发布冲突保留旧构建，重复发布不重复切换或产生矛盾审计。
4. 从 S4 升级不改变已发布 ID/hash，不重新计算索引，不扫描并自动发布已有待审任务。旧候选可显式 resume 或人工处理，原人工复核要求仍生效；登记资格只改变清单及放行报告，不改变 index_profile_hash。
5. 自动／人工两条链路均通过真实入口执行；清单、账号和数据库不可用时按错误契约处理。已实现的并发发布、权限、排序及完整引用回归通过。

#### 10.1.8 S6：从空库和上一步升级均可完整交付

**实现范围。** 补齐 seed-demo 的完整演示、配置／运行／恢复说明及验收报告，核对所有 API/命令与生成的 OpenAPI。发现业务缺陷返回所属模块修复后重跑受影响检查，不另加一套仅供演示的业务实现。

**验收标准：**

1. 空库依次 up、migrate、seed-demo、acceptance；完整执行自动导入查询、人工复核发布、更新、旧引用失效与撤回。所有业务数据通过正式入口或同一业务服务产生；不以手改表或 mock 响应完成演示。
2. 从保留测试资料的 S5 版本升级，确认 Token、来源、当前构建、父子 ID、配置和审计保持有效；同版本重启和重复迁移通过，seed-demo 重跑不重复来源、不恢复已撤回资料。
3. 第 10.4 节 I1-A01～I1-A18 **全部通过**，运行全量单元／离线契约、PostgreSQL 集成与真实 HTTP 验收。前述任一步的通过不替代完整矩阵，不能把未测分支算作该项已验收。
4. 由另一位维护者按说明完成初始化、导入、查看报告、处理待审／失败、发布及撤回；报告明确本迭代没有 Worker、笔吧处理器、向量模型或反馈能力，未调用外部平台。

### 10.2 开发任务与步骤映射

| 任务 | 所属步骤 | 具体内容 |
| --- | --- | --- |
| I1-01 | S0 | 工程骨架、依赖、容器、health、日志、pytest 配置 |
| I1-02 | S1，S2/S3 完成业务调用 | 数据模型、迁移、权限、selector、审计、初始化命令 |
| I1-03 | S1/S2，查询契约在 S4 接入 | DTO/Serializer、hash、Profile、纯解析器与处理器 |
| I1-04 | S2；S5 扩展放行后的恢复 | 同步 pipeline、事务、去重、固定输入、任务恢复 |
| I1-05 | S3/S5 | 人工／自动放行、发布、来源状态和审计 |
| I1-06 | S3 的详情、S4 的检索 | 查询预处理、关键词召回、父段聚合和引用 |
| I1-07 | S1～S5 | API 路由、管理命令和 OpenAPI，随对应能力接入 |
| I1-08 | S0～S6 | fixture、e2e、Makefile、逐步验收报告，S6 完成交接 |

I1-01～I1-08 是实现任务编号，S0～S6 是可运行交付步骤。纯解析模块仍不依赖 ORM，API／命令复用同一应用服务；步骤划分不改变第 2.2 节的依赖方向。

### 10.3 测试分层与必测行为

| 测试层 | 必测行为 | 验证边界 |
| --- | --- | --- |
| unit | 规范化／hash 与 Markdown 行尾语义，长度和 null／布尔类型，空 domain_metadata 校验、固定 concept 产物，纯处理器定位，放行决策，关键词拆词，父段聚合，状态组合 | 不访问数据库、网络或模型；预期值手工给定，不复制实现算答案 |
| contract | 请求／响应通过实际 Serializer、未知键错误路径、同步导入 200 与任务状态区分、处理器 DTO 一致、fake 改写进入召回、bypass 不调用、异常回退不改身份／过滤 | 不 mock 被测 Serializer／适配器；OpenAPI 由同一 Serializer 生成并验证示例 |
| integration | PostgreSQL 约束与锁、SQL 排序后 LIMIT、来源／权限过滤、固定输入、原子发布、审计、重复提交和恢复 | 使用隔离 PostgreSQL，不用 SQLite／mock ORM 证明事务 |
| e2e | 真实 HTTP Token＋管理命令，从空库提交、查询、复核、更新、引用到撤回及重启 | 不调用内部 Model 直接造出应由业务入口完成的状态；故障注入另在集成层完成 |

发布必须运行：

```sh
python3 -m pytest tests/unit tests/contract
python3 -m pytest tests/integration
make acceptance ITERATION=1
```

pytest 使用严格 markers，数据库测试才申请 db／transactional_db；不能用全局 autouse 打开数据库。测试名 `test_<条件>_<结果>`，以可观察行为断言。条件模块和向量模型尚未实现，不预建大批模型 mock 用例。

### 10.4 逐项验收矩阵

| 编号 | 输入／操作 | 必须观察到的结果 |
| --- | --- | --- |
| I1-A01 | 空 PostgreSQL，依次 up/migrate/init | 5 张业务表可用；没有 vector／PGroonga、Worker 或模型依赖；配置真实 hash 正确 |
| I1-A02 | 已验证配置＋已确认授权的自编短文 | 200，succeeded/approved/auto/is_current=true；一父一子正文与定位对应输入，知识类型固定 concept |
| I1-A03 | 同文去重；改标题／正文／日期；重复键但权限／复核要求不同 | 等价复用 200；内容变化生成新任务；人工 pending 新稿发布前旧构建可查；字段冲突 409，不覆盖来源或降低复核要求 |
| I1-A04 | require_manual_review=true；普通 date_unknown warning | 均返回 200；前者 status=succeeded/review_status=pending 不可查询；后者允许自动发布且返回 date_unknown，不能将所有 warning 当阻断 |
| I1-A05 | 配置未列入放行清单；随后人工 review/publish | 未确认配置的候选不自动上线；通过样本核对后可人工发布，硬错误无法批准 |
| I1-A06 | 授权／脱敏未确认，或 wechat/product_review 输入 | 400，正文未入库、不调用平台／网络；不将渠道改成 manual 静默接收 |
| I1-A07 | 预期构建失败、T2 中断、T2 后发布中断 | 预期失败返回 200/status=failed，无部分产物；中断 pending 经 resume 恢复；成功产物不重写，发布幂等；rejected 不被 retry/resume 绕过 |
| I1-A08 | 同一来源两个有效候选依次发布 | 首个成功，后者 base_build 冲突 409；并发测试没有部分指针或产物 |
| I1-A09 | 同 query 下有多个匹配样本和相同分数 | PostgreSQL 排序后取候选，稳定 ID 破平局，contexts 按父段去重，top_k 正确 |
| I1-A10 | NoOp、bypass、fake 改写／超时 | query_id 与 hash 有效；正式 mode=keyword；回退保留输入与范围，空且降级为 insufficient_evidence |
| I1-A11 | 非法数组/null/未知键；合法 purchase 或非空条件 | 格式错误为 400 INVALID_ARGUMENT；本阶段未实现能力为 400 CAPABILITY_NOT_AVAILABLE，不静默忽略 |
| I1-A12 | public/internal 同词文档、无权来源过滤、候选／旧 ID | 普通账号不泄露内部标题；内部账号可见；来源过滤不扩大权限；旧／无权详情统一 404 |
| I1-A13 | 撤回、停用、public→internal、授权撤销、返回前变化 | 已提交变化约束查询及父子详情；在途复核移除失效项；internal→public 修改被拒绝 |
| I1-A14 | 超输入限制／返回预算；正文含“忽略权限” | 输入明确拒绝；响应整父段跳过并标记，不截断引用；正文指令不会触发管理动作 |
| I1-A15 | 省略／空／非空 domain_metadata；按知识类型查询 | 省略与 {} 等价；null、其他类型及任意非空对象均 400，包括 knowledge_type／conflicts；产物固定 concept；过滤集合不含 concept 时正常无结果；无 conflict_key 或 conflict 标志 |
| I1-A16 | 数据库故障、审计写失败、重启、重复 migrate | 必要依赖失败返回 503；管理事务不半提交；重启数据保留，迁移幂等 |
| I1-A17 | 反馈端点、查询记录、报告与文档 | feedback_available=false、反馈端点 404，无查询表；报告有父子／定位／状态，命令与 OpenAPI 实例可用 |
| I1-A18 | Markdown 含行尾两个空格、代码缩进、BOM／CRLF 和首尾空白行 | 仅按第 5.2 节统一格式，保留行尾空格、缩进和中间空行；input_text、父子正文和返回 text 一致；仅改变换行符不改变 hash，删除有意义的行尾空格改变 hash；TXT 采用同一保真规则 |

### 10.5 完成定义与交接

完成条件：上述本阶段验收全通过、全量单元／离线契约及相关 PostgreSQL 测试通过、功能接入真实入口、运行说明和迁移齐全、无阻塞问题。提交验证报告记录命令、结果、环境、跳过项和已知限制；必需检查未完成时标记“验证未完成”。不把本阶段通过等同于完整首期三来源、三场景或模型指标已通过。

交付应用与锁定依赖、5 表迁移、配置清单、命令与 API、合成 fixture、测试、OpenAPI、示例质量报告、运行／恢复说明。迭代二接入 Worker 时复用 submit_import、固定任务输入、纯处理器 DTO、发布服务和引用协议，替换调度／词法后端；笔吧处理器按其独立 Schema 开发，不修改 GenericNoteProcessor 来承担平台专用逻辑。
