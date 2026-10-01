# 迭代一实施记录

用户请求：依据 `phase1-iteration1-implementation.md` 的 S0～S6 分步实现，完成必要验收与 reviewer 评审，每步单独以 Conventional Commits 提交，不堆积大量修改。

依据：实现文档 v0.3、首期技术设计和项目单元测试规范。保持 manual/generic_note、一父一子、concept、空 domain_metadata、Markdown 行尾语义和同步 HTTP 200；不实现笔吧、Worker、向量、Agent、反馈，不改 `.gitignore`。

初始状态：`master`，基线 `cc97d34`，工作区干净。主机 Python 3.10，全部应用验证在固定 Python 3.12／PostgreSQL 17 的隔离 Compose 项目完成。技能原引用路径失效，使用 `/home/kurfuerst/.agents/skills/implementation-review-loop/SKILL.md`。

| 步骤 | 能力 | 验证／评审／提交 |
| --- | --- | --- |
| S0 | 容器、依赖、健康检查、日志和验收入口 | 验证通过；第 1 轮只读评审无阻塞 |
| S1 | 五表、配置、身份与初始化 | 验证通过；第 1 轮只读评审无阻塞 |
| S2 | 同步导入、固定输入、报告与恢复 | 验证通过；第 1 轮有效只读评审无阻塞 |
| S3 | 人工发布、引用、撤回与更新 | 验证通过；2 轮只读评审均无阻塞 |
| S4 | 关键词检索与最终权限复核 | 已实现；70 项离线、36 项 PostgreSQL 集成、5 项真实 HTTP／命令验收通过；空库、升级、重启和 OpenAPI 严格校验通过；第 1 轮有效只读评审无阻塞 |
| S5 | 自动放行和成功构建恢复 | 已实现；76 项离线、47 项 PostgreSQL 集成、6 项真实 HTTP／命令验收通过；第 1 轮只读评审无阻塞 |
| S6 | 全量验收、演示与运行交接 | 已实现；138 项全量验收通过；第 1 轮只读评审无阻塞 |

每步细节在完成验收后追加；未完成的检查不能据此标记通过。

## S0

- 新增容器、Django 配置、依赖锁、健康检查、测试和运行说明；尚无业务路由。
- `make up`、两次 `make migrate`、`make test-unit`（6 passed）、`make acceptance STEP=S0`（1 passed）通过；STEP=S1／ITERATION=2 均按预期非零退出。
- 停止本项目 db 后 live=200、ready=503，日志记录 database_unavailable；恢复 db、down/up 后迁移保留，HTTP 验收通过。
- Python 3.12.14、Django 5.2.17、PostgreSQL 17 固定镜像；配置与报告放仓库外，未修改忽略规则。
- 专用 reviewer 角色因模型供应方不可用无法启动，改用同等只读职责的默认子智能体评审；第 1 轮 NO_BLOCKING_ISSUES。
- 提交：`feat(platform): 实现 S0 服务启动与健康验收`（提交 hash 见 Git 历史）。

## S1

- 新增 `catalog` 五表及累积迁移、Profile 校验／hash、Token 认证、visibility 权限策略、审计基础和 `kb_init`／`kb_account` 命令；仅开放受维护权限保护的 `/api/schema/`，不开放来源或查询空壳。
- `make migrate`（含 `kb_init`，重复执行幂等）、`make test-unit`（13 passed）、`make test-integration`（3 passed）、`make acceptance STEP=S1`（2 passed）通过；迁移 `makemigrations --check --dry-run` 无漂移。
- 集成测试使用真实 PostgreSQL 验证五表约束、单例、FK、配置冲突、Token 文件 0600、撤销和 `is_staff` 不替代 `read_internal`；真实 HTTP 验证无 Token=401、维护 Token=200、普通 Token=403。
- S1 仍保持 `ready=503`，尚无导入、发布、详情和查询；配置／Token 不写入仓库。
- 独立 Compose 空库完成 up／全部迁移／初始化／HTTP 验收；主项目 down/up 和重复 migrate 前后账号 ID、配置 hash 快照一致。验收另输出源码摘要、依赖版本和实际配置 hash。
- 专用 reviewer 角色沿用 S0 的模型不可用限制，默认只读 reviewer 第 1 轮 `NO_BLOCKING_ISSUES`。
- 提交：`feat(catalog): 实现 S1 存储初始化与账号权限`（提交 hash 见 Git 历史）。

## S2

- 新增严格 Serializer、保真规范化／内容 hash、纯解析器／处理器与 DTO、同步 T1/T2 编排、来源锁去重、维护 selector／报告、四个 API、`kb_import`／`kb_job` 和合成样本。所有候选保持 pending，未提前发布。
- `make test-unit` 35 passed、`make test-integration` 15 passed、`make acceptance STEP=S2` 3 passed。覆盖并发首建去重、Markdown 保真、失败／中断回滚与恢复、固定输入／成功父子 ID、权限／复核冲突、审计失败、维护模式和大小限制；OpenAPI 使用实际 Serializer 验证。
- 验收发现并修复了空元数据字段在 OpenAPI 中被省略的问题。未连接外部资料／模型；失败注入只在测试中，HTTP／命令主链路使用真实服务和 PostgreSQL。
- 独立项目 `itxia-phase1-s2fresh` 从空库 up／全部迁移／init／S2 验收通过；主项目重启及重复迁移前后账号、Token 摘要、来源／任务／父子 ID、内容／配置 hash 和审计快照一致，再次 S2 HTTP 验收通过。
- Django 系统检查、`makemigrations --check --dry-run` 和 `spectacular --validate --fail-on-warn` 均通过。
- 评审启动曾三次遇到模型容量不足，随后原模型恢复，未切换模型；第 1 轮有效只读评审 `NO_BLOCKING_ISSUES`。
- 提交：`feat(ingestion): 实现 S2 同步候选导入与恢复`（提交 hash 见 Git 历史）。

## S3

- 新增人工复核、原子发布、来源 PATCH／withdraw、当前父／子详情与三个管理命令；统一按来源→任务加锁，发布指针和审计同事务提交。纯产物校验提取到 contracts，构建快照校验归 catalog，避免反向依赖导入模块。
- 全量单元／契约 35 passed、真实 PostgreSQL 集成 26 passed、HTTP／命令 S3 验收 4 passed；覆盖候选与旧 ID 不可见、人工放行、更新、三种限权、撤回终态、审计回滚和并发发布。
- 系统检查、迁移无漂移通过；OpenAPI 曾发现不同 status 枚举命名碰撞，使用明确枚举名称修复后严格校验无警告，字段约束未放宽。
- 独立空库项目 up／迁移／init／S3 验收通过。S2 留存的账号／Token 摘要、来源／任务／父子 ID／hash 和审计均保留；一个 S2 候选通过真实管理命令直接复核发布，父子 ID 不变。
- 主项目 down/up、重复 migrate 前后完整状态快照一致；随后 S3 HTTP／命令验收再次 4 passed。
- 两轮只读评审均为 `NO_BLOCKING_ISSUES`，第 2 轮检查配置枚举命名修复与最终文档。
- 提交：`feat(publish): 实现 S3 人工发布与父子引用`（提交 hash 见 Git 历史）。

## S4

- 新增严格查询 Serializer（general／空条件子集）、NoOp／bypass／失败回退处理器协议、PostgreSQL 参数化关键词后端、SearchScope、父段聚合和 64 KiB 整段预算；新增 `POST /api/v1/search/`，ready 在配置与查询后端可用时返回 200。
- 查询只读取当前 active、授权 confirmed、已发布且与活动 IndexProfile 匹配的父段；按证据分数、稳定 ID 在数据库排序后取候选，再按父段返回完整正文和全部引用，最终再次读取账号与当前指针。
- `domain_metadata`、场景条件和反馈仍未参与查询；本步固定 concept/general，响应 `feedback_available=false`。没有引入向量、LLM、Worker 或 QueryRecord。
- `make test-unit` 70 passed、`make test-integration` 36 passed、`make acceptance STEP=S4` 5 passed；独立空库、S3 数据升级／重启和留存发布资料检索均通过。`spectacular --validate --fail-on-warn`、`makemigrations --check --dry-run` 和 Django system check 通过。
- 旧 S0～S3 断言已按真实开放的 search 路由更新；README、AGENTS 和实施文档入口同步到 S4。专用 reviewer 角色因模型供应方不可用未能启动，默认只读 reviewer 第 1 轮有效评审为 `NO_BLOCKING_ISSUES`。
- 提交：`feat(retrieval): 实现 S4 关键词检索与父段返回`（hash 见 Git 历史）。

## S5

- 增加受版本管理的自动资格清单校验和合成样本核对记录，`try_auto_release` 在硬校验后记录系统账号批准；导入／retry／resume 统一恢复 T3 并调用既有发布事务。
- 主动人工复核和无匹配资格保持候选；date_unknown 不阻断；已有人工结论不覆盖。自动批准尚未发布时重验清单，资格失效或 base_build 冲突保留旧指针与成功产物，并记录安全错误。清单删除不自动撤回历史发布。
- `make test-unit` 76 passed、`make test-integration` 47 passed、`make acceptance STEP=S5` 6 passed；覆盖 T2 完成／自动批准后中断、清单／账号不可用、自动审核／发布审计失败、幂等恢复与人工拒绝不可绕过。
- S4→S5 初始化前后状态摘要一致，未重建、未扫描发布旧候选；独立空库初始化与 6 项真实入口验收通过。主项目重启＋重复迁移后摘要一致，HTTP 验收再次 6 passed；OpenAPI 严格校验、系统检查和迁移无漂移通过。
- 第 1 轮只读评审 `NO_BLOCKING_ISSUES`。reviewer 自身 Docker socket 受限，测试依据主智能体实跑记录；主智能体验证无跳过。
- 提交：`feat(ingestion): 实现 S5 自动放行与发布恢复`（hash 见 Git 历史）。

## S6

- 新增 `kb_seed_demo` 和运行交接手册；演示账号、公开／内部／待审合成资料均通过正式服务创建，重复 seed 不复制、不覆盖后续修改、不恢复撤回。
- 修复 pytest 跨目录同名测试模块的收集冲突，统一使用 `--import-mode=importlib`；`scripts/acceptance.py --step S6` 组合全部测试层和 demo HTTP 验收。
- `make acceptance ITERATION=1` 138 passed（76 离线、55 PostgreSQL 集成、7 真实入口）；S5 升级摘要一致，独立空库和同版本重启后全量验收均 138 passed；重复迁移与摘要一致、seed 重跑、OpenAPI 严格校验／系统检查／迁移无漂移均通过。逐项 I1-A01～I1-A18 见 [验收报告](iteration1-acceptance-report.md)。
- 运行和故障交接见 [运行手册](iteration1-runbook.md)。独立 reviewer 已按手册用唯一合成前缀完成初始化、导入、报告、人工复核／发布、resume、查询和撤回；未声称真人已试用。实际停数据库时 live=200、ready/search=503，恢复后 ready/search=200。第 1 轮只读评审 `NO_BLOCKING_ISSUES`；reviewer 独立重跑 S6 验收 138 passed。
- 提交：`feat(delivery): 完成 S6 演示与全量验收`（hash 见 Git 历史）。
